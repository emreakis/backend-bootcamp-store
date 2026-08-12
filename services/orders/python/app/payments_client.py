"""THE FILE THE SESSION 3 EXERCISE LIVES IN.

The gRPC half of this service's dependencies, and the one that will take the store
down with it if you let it. Everything below `charge` is the shape of a remote call
that has not yet been made safe.

Try it. Both of these hang, and neither of them should::

    docker compose stop payments                              # payments is DOWN
    PAYMENT_LATENCY_MS=30000 docker compose up -d payments    # payments is SLOW

The first one surprises people. Surely a stopped server refuses connections and the
call fails at once? Not on a container network: nothing is listening, the SYN packets
are dropped rather than refused, and the connection attempt waits for a TCP timeout
measured in minutes. "Down" and "slow" are the same thing to a caller with no deadline
— which is why the deadline, not the outage, is the thing to fix.

Meanwhile `GET /health` on this service keeps answering 200, because orders is not
sick. Its dependency is. Watching a completely healthy service become unusable anyway
is the moment Session 3 exists for, and it is the fallacy from Session 1 — *the
network is reliable* — collecting its debt.

There is no generated code in this directory and none in git. The Dockerfile runs
protoc over ../../../contracts/proto before it copies a line of this file, so
`payments_pb2` below is the contract, compiled.
"""

import logging

import grpc
from bootcamp.payments.v1 import payments_pb2, payments_pb2_grpc

from . import config, problems

log = logging.getLogger("orders.payments")

# The channel is built once and reused for the life of the process.
#
# It is not a connection. It is a managed thing that resolves the name, opens
# connections as needed, multiplexes concurrent calls over HTTP/2 and reconnects on
# its own after a failure. Building one per request is both slow and a
# misunderstanding of what it is.
#
# `payments` is not a hostname anybody configured — it is a service name the platform
# resolves. Plaintext because this hop is inside the cluster; in production a service
# that moves money gets mTLS.
_channel = grpc.insecure_channel(config.PAYMENTS_ADDR)
_stub = payments_pb2_grpc.PaymentsStub(_channel)

log.info("payments client -> %s (timeout %s ms, retries %s)",
         config.PAYMENTS_ADDR, config.PAYMENTS_TIMEOUT_MS, config.PAYMENTS_RETRY_MAX)


def charge(order_id: str, amount_cents: int, idempotency_key: str) -> tuple[str, str]:
    """Charge the card.

    `idempotency_key` is what makes this call safe to repeat, and is therefore the
    precondition for exercise 3.2. Retrying a charge without one bills the customer
    twice.
    """
    request = payments_pb2.ChargeRequest(
        order_id=order_id,
        amount_cents=amount_cents,
        currency="EUR",
        idempotency_key=idempotency_key,
    )

    try:
        # ================================================================
        # TODO (exercise 3.1) — GIVE THIS CALL A DEADLINE.       [do this first]
        #
        # `_stub.Charge(request)` waits forever. Not "a long time" — forever. The
        # default value of a missing deadline is the worst value it could have, and
        # it is the single most important line missing from this file.
        #
        # Every gRPC stub takes one, in every language. In Python it is a keyword
        # argument, in SECONDS rather than milliseconds:
        #
        #     _stub.Charge(request, timeout=config.PAYMENTS_TIMEOUT_MS / 1000)
        #
        # Note it is per CALL, not per client. There is no way to set it once on the
        # stub and forget it, and that is deliberate across every gRPC library: a
        # deadline is a property of the request you are making right now, not of the
        # connection you happen to be making it over.
        #
        # The deadline also travels: payments sees the caller's remaining budget and
        # abandons its own work when the budget runs out, instead of finishing an
        # answer nobody is listening for. Watch the payments log say
        # "ABANDONED: context canceled" the moment this expires.
        #
        # Verify: PAYMENT_LATENCY_MS=30000, then POST an order. Before, it hangs;
        # after, you get a 503 in two seconds.
        # ================================================================

        # ================================================================
        # TODO (exercise 3.2) — RETRY, BUT ONLY BECAUSE YOU MAY.       [then this]
        #
        # Wrap the call in a bounded retry: at most `config.PAYMENTS_RETRY_MAX` extra
        # attempts, with backoff between them (say 50 ms, then 200 ms), and ONLY for
        # grpc.StatusCode.UNAVAILABLE and grpc.StatusCode.DEADLINE_EXCEEDED.
        #
        # Three rules, each of which someone learns the hard way:
        #
        #   1. Only retry what is safe to repeat. This call is, because ChargeRequest
        #      carries an idempotency key and payments returns the original response
        #      for a key it has seen. Delete that field and this exercise becomes a
        #      double-billing bug.
        #
        #   2. Never retry a business outcome. A declined card will be declined
        #      again; retrying it just costs the customer time.
        #
        #   3. Bound it, and back off. Retrying into an overloaded service is how a
        #      brownout becomes an outage — you add load to the exact system that is
        #      failing from load. Three attempts and a budget, not "retry until
        #      success".
        #
        # Note also that a retry multiplies your latency budget: three attempts at a
        # 2 s deadline is a 6 s worst case, which is probably longer than the caller
        # above you is prepared to wait. Real systems give the whole operation one
        # budget and spend it down.
        # ================================================================

        # ================================================================
        # TODO (exercise 3.3) — PUT A CIRCUIT BREAKER IN FRONT.        [last]
        #
        # Count consecutive failures. At `config.BREAKER_FAILURE_THRESHOLD`, stop
        # calling payments at all and fail immediately for `config.BREAKER_RESET_MS`;
        # then let one probe through and close on success.
        #
        # A breaker does two jobs, and the second is the one people forget:
        #
        #   * it turns a slow hang into an instant, designed failure, so orders stops
        #     burning threads on a call it can predict will fail; and
        #   * it takes load OFF payments, giving it room to recover. Without one, a
        #     struggling service is held under by the traffic of everyone politely
        #     waiting for it.
        #
        # Remember this process serves requests from a thread pool, so your counter
        # is shared mutable state across threads. Reach for a threading.Lock, or use
        # `pybreaker`, which does this properly. Writing the twenty lines yourself
        # once is worth doing first, because then you know what it is doing.
        # ================================================================

        response = _stub.Charge(request)

    except grpc.RpcError as transport_failure:
        code = transport_failure.code()
        log.warning("order=%s charge failed at the transport: %s", order_id, code)

        # Transport-level trouble. The customer did nothing wrong, so this is a 5xx
        # and carries Retry-After. Crucially, NO CHARGE WAS MADE — or if one was, the
        # idempotency key means the retry will find it rather than duplicate it.
        if code in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
            raise problems.payments_unavailable(
                f"The payment service did not respond within "
                f"{config.PAYMENTS_TIMEOUT_MS} ms. No charge was made.")

        # Anything else — INVALID_ARGUMENT, UNIMPLEMENTED — means we sent something
        # wrong, which is our bug and not a retry candidate.
        raise RuntimeError(f"payments rejected the request: {code}")

    # A DECLINE IS NOT A FAILURE. The call succeeded; the answer was "no".
    #
    # Payments deliberately returns OK with status DECLINED rather than a gRPC error
    # code, so that no retry policy in the system ever re-attempts a decision that
    # will never change. Here that becomes a 402 — the customer's problem to solve,
    # and not ours.
    if response.status == payments_pb2.CHARGE_STATUS_DECLINED:
        log.info("order=%s charge DECLINED: %s", order_id, response.decline_reason)
        raise problems.payment_declined(
            response.decline_reason or "The card was declined.")

    log.info("order=%s charge APPROVED auth=%s", order_id, response.auth_code)
    return "APPROVED", response.auth_code
