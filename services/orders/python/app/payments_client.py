"""SOLUTION — exercises 3.1, 3.2 and 3.3.

Compare with the same file on `main`::

    git diff main solution -- services/orders/python

Three things arrived, in the order they matter. A deadline, so a slow payments service
cannot hold a checkout open forever. A bounded retry, legal only because ``Charge``
carries an idempotency key. And a breaker, so that once payments is clearly unwell we
stop asking — which fails fast for us and takes load off it.

The first of those is worth more than the other two together. Delete the retry and the
breaker and this service still degrades honestly; delete the deadline and nothing else
here can save it.
"""

import logging
import threading
import time

import grpc
from bootcamp.payments.v1 import payments_pb2, payments_pb2_grpc

from . import config, problems

log = logging.getLogger("orders.payments")

# Backoff between attempts. Never zero — an instant retry is just a second failure.
BACKOFF_MS = (50, 200, 800)

# The two codes that mean "try again": nobody answered, or somebody answered too slowly.
RETRYABLE = (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED)

_channel = grpc.insecure_channel(config.PAYMENTS_ADDR)
_stub = payments_pb2_grpc.PaymentsStub(_channel)

log.info("payments client -> %s (timeout %s ms, retries %s, breaker %s/%s ms)",
         config.PAYMENTS_ADDR, config.PAYMENTS_TIMEOUT_MS, config.PAYMENTS_RETRY_MAX,
         config.BREAKER_FAILURE_THRESHOLD, config.BREAKER_RESET_MS)


class CircuitBreaker:
    """Exercise 3.3 — closed, open, or half-open.

    Half-open is the state people forget, and leaving it out is worse than having no
    breaker at all: a breaker that never closes again is a permanent outage you built
    yourself. After ``reset_ms`` this lets exactly one request through; if it succeeds
    the breaker closes, and if it fails the clock restarts.

    The lock is not decoration. FastAPI runs `def` handlers on a thread pool, so this
    counter really is shared mutable state — and an unsynchronised one is a bug that
    only shows up under load, which is the only time this code matters.
    """

    def __init__(self, threshold: int, reset_ms: int):
        self._threshold = threshold
        self._reset_seconds = reset_ms / 1000.0
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False                                  # closed
            if time.monotonic() - self._opened_at >= self._reset_seconds:
                log.info("circuit breaker HALF-OPEN: letting one probe through")
                self._opened_at = None                        # half-open
                return False
            return True                                       # open

    def record_success(self) -> None:
        with self._lock:
            if self._consecutive_failures:
                log.info("circuit breaker CLOSED after a success")
            self._consecutive_failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._threshold and self._opened_at is None:
                self._opened_at = time.monotonic()
                log.warning("circuit breaker OPEN after %d consecutive failures; "
                            "not calling payments for %d ms",
                            self._consecutive_failures, config.BREAKER_RESET_MS)


_breaker = CircuitBreaker(config.BREAKER_FAILURE_THRESHOLD, config.BREAKER_RESET_MS)


def charge(order_id: str, amount_cents: int, idempotency_key: str) -> tuple[str, str]:
    """Charge the card, with a deadline, a bounded retry and a breaker in front."""
    request = payments_pb2.ChargeRequest(
        order_id=order_id,
        amount_cents=amount_cents,
        currency="EUR",
        idempotency_key=idempotency_key,
    )

    # EXERCISE 3.3 — the breaker, checked before anything else.
    #
    # If payments has failed BREAKER_FAILURE_THRESHOLD times in a row we do not call it
    # at all. That is not pessimism, it is arithmetic: the next call will almost
    # certainly fail too, and it would cost us the full timeout per attempt to find out
    # while adding load to a service that is already struggling.
    if _breaker.is_open():
        log.warning("order=%s charge SKIPPED: circuit breaker is open", order_id)
        raise problems.payments_unavailable(
            "The payment service is not answering, so we stopped calling it. "
            "No charge was made.")

    last_code = None

    # EXERCISE 3.2 — a BOUNDED retry.
    #
    # At most PAYMENTS_RETRY_MAX extra attempts, and only for the two retryable codes.
    # Never for a decline, which is not a failure, and never for INVALID_ARGUMENT, which
    # is our bug and will be our bug again next time.
    #
    # This is only legal because ChargeRequest carries an idempotency key and payments
    # returns the original response for a key it has seen. Take that away and this loop
    # bills the customer up to three times.
    for attempt in range(config.PAYMENTS_RETRY_MAX + 1):
        try:
            # ============================================================
            # EXERCISE 3.1 — THE DEADLINE. The most important line in this file.
            #
            # Python's gRPC takes it as a duration in SECONDS, per call. There is no way
            # to set it once on the stub, and that is deliberate in every gRPC library:
            # a deadline belongs to the request you are making right now.
            #
            # It is PER ATTEMPT, which means the worst case is retries + 1 attempts plus
            # backoff: with the defaults, 3 x 2000 ms + 250 ms ~ 6.25 s. State that
            # number out loud, because whoever calls checkout has their own budget.
            #
            # The other defensible design is one deadline shared by all attempts. That
            # keeps the promise at 2 s but means a slow dependency eats the whole budget
            # on attempt one and the retries never happen — which is the honest lesson
            # underneath: retries fix TRANSIENT failures, not slow ones.
            # ============================================================
            response = _stub.Charge(request, timeout=config.PAYMENTS_TIMEOUT_MS / 1000.0)

        except grpc.RpcError as transport_failure:
            code = transport_failure.code()

            if code not in RETRYABLE:
                # Not retryable, and not the breaker's business either: we sent
                # something wrong and sending it again will not help.
                raise RuntimeError(f"payments rejected the request: {code}")

            last_code = code
            _breaker.record_failure()
            log.warning("order=%s charge attempt %d/%d failed: %s",
                        order_id, attempt + 1, config.PAYMENTS_RETRY_MAX + 1, code)

            if attempt < config.PAYMENTS_RETRY_MAX:
                time.sleep(BACKOFF_MS[min(attempt, len(BACKOFF_MS) - 1)] / 1000.0)
            continue

        _breaker.record_success()

        # A DECLINE IS NOT A FAILURE. The call succeeded; the answer was "no". It does
        # not count against the breaker and it is never retried.
        if response.status == payments_pb2.CHARGE_STATUS_DECLINED:
            log.info("order=%s charge DECLINED: %s", order_id, response.decline_reason)
            raise problems.payment_declined(
                response.decline_reason or "The card was declined.")

        log.info("order=%s charge APPROVED auth=%s (attempt %d)",
                 order_id, response.auth_code, attempt + 1)
        return "APPROVED", response.auth_code

    # Out of attempts. NO CHARGE WAS MADE — or if one was, the idempotency key means a
    # later retry finds it rather than duplicating it. 503 with Retry-After, because the
    # customer did nothing wrong.
    raise problems.payments_unavailable(
        f"The payment service did not respond ({last_code}) after "
        f"{config.PAYMENTS_RETRY_MAX + 1} attempts of {config.PAYMENTS_TIMEOUT_MS} ms. "
        "No charge was made.")
