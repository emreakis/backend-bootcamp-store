"""PAYMENTS — a gRPC service, and the only one in the system with no HTTP surface and
no database.

Nothing outside the store ever calls it, which is why it does not need REST: there is
no browser to please, no cache to negotiate with, and no human reading its responses.
What it does need is a contract that cannot drift and a wire format that is cheap on a
hot path, and that is the case for gRPC in one sentence.

Read this next to services/catalog/python — the same amount of work, an entirely
different shape, and the difference is who the caller is.
"""

import logging
import os
import secrets
import threading
import uuid
from concurrent import futures

import grpc
from bootcamp.payments.v1 import payments_pb2, payments_pb2_grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection

IMPLEMENTATION = "python"

PORT = os.getenv("PORT", "50051")
DECLINE_OVER_CENTS = int(os.getenv("PAYMENT_DECLINE_OVER_CENTS", "500000"))
ALWAYS_DECLINE = os.getenv("PAYMENT_ALWAYS_DECLINE", "false") == "true"
# The exercise dial. Set it above the caller's deadline and payments stops being down
# and starts being SLOW — which is the failure that actually hurts, because a slow
# service accepts your connection and then holds it.
LATENCY_MS = int(os.getenv("PAYMENT_LATENCY_MS", "0"))

log = logging.getLogger("payments")


class Payments(payments_pb2_grpc.PaymentsServicer):
    """Implements the generated servicer.

    Inheriting from the generated base class is not boilerplate — it is forward
    compatibility. Add a method to the .proto tomorrow and this still runs, serving
    UNIMPLEMENTED for the new one instead of failing to start.
    """

    def __init__(self):
        # Idempotency, in memory.
        #
        # A restart forgets every key, and that is a real limitation left visible rather
        # than hidden. In production this is a datastore with a TTL, and "where do
        # idempotency records live, and for how long" is a design question with real
        # answers. Here it is a dict, so you can see the shape of the idea.
        #
        # The lock is not decoration: this server runs a thread pool, so two concurrent
        # retries of the same key really can arrive at once.
        self._lock = threading.Lock()
        self._charges: dict[str, payments_pb2.ChargeResponse] = {}

    def Charge(self, request, context):
        """Unary: one request, one reply."""
        # Idempotency first, before any work. A repeat of a key we have seen returns the
        # ORIGINAL answer and charges nothing — which is the entire reason the caller is
        # allowed to retry this method automatically.
        if request.idempotency_key:
            with self._lock:
                previous = self._charges.get(request.idempotency_key)
            if previous is not None:
                log.info("charge order=%s idempotency_key=%s REPLAYED",
                         request.order_id, request.idempotency_key)
                return previous

        # Injected latency, applied while still watching the caller's deadline. If the
        # caller gave up, so do we — continuing to work for a client that has stopped
        # listening is how an overloaded system stays overloaded.
        #
        # `context.add_callback` fires when the RPC terminates for any reason, deadline
        # included, so waiting on that Event is how Python spells Go's
        # `select { case <-time.After(d): case <-ctx.Done(): }`.
        if LATENCY_MS > 0:
            abandoned = threading.Event()
            context.add_callback(abandoned.set)
            if abandoned.wait(LATENCY_MS / 1000.0):
                log.info("charge order=%s ABANDONED: context canceled", request.order_id)
                return payments_pb2.ChargeResponse()

        if request.amount_cents <= 0:
            # A malformed request IS an RPC error, and INVALID_ARGUMENT is the gRPC
            # equivalent of a 400. Contrast with the decline below.
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          f"amount_cents must be positive, got {request.amount_cents}")

        declined = ALWAYS_DECLINE or request.amount_cents > DECLINE_OVER_CENTS

        # THE DESIGN DECISION IN THIS FILE.
        #
        # A declined card is not an RPC failure. The call succeeded: we asked the
        # provider, the provider said no, and that answer arrived intact. So this returns
        # OK with status DECLINED, and NOT context.abort(PERMISSION_DENIED, ...).
        #
        # The distinction matters more than it looks. gRPC error codes are how the
        # *transport* reports trouble, and clients quite reasonably retry some of them.
        # Encode a business outcome as one and every retry policy in the system starts
        # re-attempting a decision that will never change — while a genuinely retryable
        # UNAVAILABLE becomes indistinguishable from "this card is stolen".
        #
        # Business outcomes go in the response. Failures go in the status.
        response = payments_pb2.ChargeResponse(payment_id=str(uuid.uuid4()))
        if declined:
            response.status = payments_pb2.CHARGE_STATUS_DECLINED
            response.decline_reason = (
                f"amount exceeds the approval limit of {DECLINE_OVER_CENTS} cents")
        else:
            response.status = payments_pb2.CHARGE_STATUS_APPROVED
            response.auth_code = "AUTH-" + secrets.token_hex(4).upper()

        if request.idempotency_key:
            with self._lock:
                self._charges[request.idempotency_key] = response

        log.info("charge order=%s amount=%d status=%s", request.order_id,
                 request.amount_cents,
                 payments_pb2.ChargeStatus.Name(response.status))
        return response

    def WatchStatus(self, request, context):
        """Server streaming, declared in the contract and deliberately not built.

        UNIMPLEMENTED is a defined, catchable answer meaning "this exists in the contract
        and not yet in this deployment". That is a far better thing for a consuming team
        to receive than a method that hangs or returns an empty stream, and it is what
        lets a contract legitimately run ahead of its implementations.
        """
        context.abort(grpc.StatusCode.UNIMPLEMENTED,
                      "WatchStatus is declared in payments.v1 but not implemented "
                      "in this deployment")


def serve():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    # Ten threads, and that number is a capacity decision rather than a default.
    #
    # Python's gRPC server is thread-per-request: every in-flight Charge holds one of
    # these, so eleven concurrent slow calls means the eleventh waits. Set
    # PAYMENT_LATENCY_MS high and this server runs out of workers long before it runs
    # out of anything else — a bounded pool being exactly the sort of resource a caller
    # without a deadline exhausts on your behalf.
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    payments_pb2_grpc.add_PaymentsServicer_to_server(Payments(), server)

    # The standard gRPC health service. gRPC has its own health-checking protocol rather
    # than borrowing HTTP's, so orchestrators probe it the same way in every language.
    # Liveness only, same rule as the REST services: it reports on this process, never on
    # its dependencies.
    health_servicer = health.HealthServicer()
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)

    # Reflection lets grpcurl explore this server with no .proto file in hand:
    #     grpcurl -plaintext localhost:50051 list
    # Convenient in a classroom, and worth disabling in production.
    reflection.enable_server_reflection((
        payments_pb2.DESCRIPTOR.services_by_name["Payments"].full_name,
        health_pb2.DESCRIPTOR.services_by_name["Health"].full_name,
        reflection.SERVICE_NAME,
    ), server)

    server.add_insecure_port(f"[::]:{PORT}")
    server.start()
    log.info("payments (%s) listening on :%s  decline_over=%d latency=%dms",
             IMPLEMENTATION, PORT, DECLINE_OVER_CENTS, LATENCY_MS)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
