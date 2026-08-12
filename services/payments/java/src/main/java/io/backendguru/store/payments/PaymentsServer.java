package io.backendguru.store.payments;

import java.security.SecureRandom;
import java.util.HexFormat;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import io.backendguru.store.payments.v1.ChargeRequest;
import io.backendguru.store.payments.v1.ChargeResponse;
import io.backendguru.store.payments.v1.ChargeStatus;
import io.backendguru.store.payments.v1.PaymentStatus;
import io.backendguru.store.payments.v1.PaymentsGrpc;
import io.backendguru.store.payments.v1.WatchStatusRequest;
import io.grpc.Context;
import io.grpc.Server;
import io.grpc.ServerBuilder;
import io.grpc.Status;
import io.grpc.health.v1.HealthCheckResponse.ServingStatus;
import io.grpc.protobuf.services.HealthStatusManager;
import io.grpc.protobuf.services.ProtoReflectionServiceV1;
import io.grpc.stub.StreamObserver;

/**
 * PAYMENTS — a gRPC service, and the only one in the system with no HTTP surface and no
 * database.
 *
 * <p>Nothing outside the store ever calls it, which is why it does not need REST: there
 * is no browser to please, no cache to negotiate with, and no human reading its
 * responses. What it does need is a contract that cannot drift and a wire format that is
 * cheap on a hot path, and that is the case for gRPC in one sentence.
 *
 * <p>Note that there is no Spring here. This service has no HTTP surface, no
 * configuration binding and nothing to inject; it is a {@code main} that starts a gRPC
 * server. The other Java services in this repo are Spring applications because they
 * serve REST and talk to a database. This one would be carrying a framework for the sake
 * of carrying one.
 */
public final class PaymentsServer {

    static final String IMPLEMENTATION = "java";

    private static final SecureRandom RANDOM = new SecureRandom();

    public static void main(String[] args) throws Exception {
        int port = Integer.parseInt(env("PORT", "50051"));
        long declineOverCents = Long.parseLong(env("PAYMENT_DECLINE_OVER_CENTS", "500000"));
        boolean alwaysDecline = "true".equals(env("PAYMENT_ALWAYS_DECLINE", "false"));
        // The exercise dial. Set it above the caller's deadline and payments stops being
        // down and starts being SLOW — which is the failure that actually hurts, because
        // a slow service accepts your connection and then holds it.
        long latencyMs = Long.parseLong(env("PAYMENT_LATENCY_MS", "0"));

        // The standard gRPC health service. gRPC has its own health-checking protocol
        // rather than borrowing HTTP's, so orchestrators probe it the same way in every
        // language. Liveness only, same rule as the REST services: it reports on this
        // process, never on its dependencies.
        HealthStatusManager health = new HealthStatusManager();
        health.setStatus("", ServingStatus.SERVING);

        Server server = ServerBuilder.forPort(port)
                .addService(new PaymentsService(declineOverCents, alwaysDecline, latencyMs))
                .addService(health.getHealthService())
                // Reflection lets grpcurl explore this server with no .proto file in
                // hand: `grpcurl -plaintext localhost:50051 list`. Convenient in a
                // classroom, and worth disabling in production.
                .addService(ProtoReflectionServiceV1.newInstance())
                .build()
                .start();

        System.out.printf("payments (%s) listening on :%d  decline_over=%d latency=%dms%n",
                IMPLEMENTATION, port, declineOverCents, latencyMs);
        server.awaitTermination();
    }

    private static String env(String key, String fallback) {
        String value = System.getenv(key);
        return value == null || value.isBlank() ? fallback : value;
    }

    /**
     * Extends the generated base class.
     *
     * <p>That is not boilerplate — it is forward compatibility. Add a method to the
     * .proto tomorrow and this still compiles, serving UNIMPLEMENTED for the new one
     * instead of failing to build.
     */
    static final class PaymentsService extends PaymentsGrpc.PaymentsImplBase {

        private final long declineOverCents;
        private final boolean alwaysDecline;
        private final long latencyMs;

        /**
         * Idempotency, in memory.
         *
         * <p>A restart forgets every key, and that is a real limitation left visible
         * rather than hidden. In production this is a datastore with a TTL, and "where
         * do idempotency records live, and for how long" is a design question with real
         * answers. Here it is a map, so you can see the shape of the idea.
         *
         * <p>Concurrent because gRPC serves every call on a pool thread, so two retries
         * of the same key really can arrive at once.
         */
        private final Map<String, ChargeResponse> charges = new ConcurrentHashMap<>();

        PaymentsService(long declineOverCents, boolean alwaysDecline, long latencyMs) {
            this.declineOverCents = declineOverCents;
            this.alwaysDecline = alwaysDecline;
            this.latencyMs = latencyMs;
        }

        /** Unary: one request, one reply. */
        @Override
        public void charge(ChargeRequest request, StreamObserver<ChargeResponse> responder) {
            // Idempotency first, before any work. A repeat of a key we have seen returns
            // the ORIGINAL answer and charges nothing — which is the entire reason the
            // caller is allowed to retry this method automatically.
            String key = request.getIdempotencyKey();
            if (!key.isEmpty()) {
                ChargeResponse previous = charges.get(key);
                if (previous != null) {
                    System.out.printf("charge order=%s idempotency_key=%s REPLAYED%n",
                            request.getOrderId(), key);
                    responder.onNext(previous);
                    responder.onCompleted();
                    return;
                }
            }

            // Injected latency, applied while still watching the caller's deadline. If
            // the caller gave up, so do we — continuing to work for a client that has
            // stopped listening is how an overloaded system stays overloaded.
            //
            // io.grpc.Context is how Java spells Go's ctx: it carries the deadline, it
            // is cancelled when the client goes away, and a listener on it is what turns
            // "sleep for a while" into "sleep for a while OR until nobody is waiting".
            if (latencyMs > 0) {
                CountDownLatch abandoned = new CountDownLatch(1);
                Context.CancellationListener listener = context -> abandoned.countDown();
                Context.current().addListener(listener, Runnable::run);
                try {
                    if (abandoned.await(latencyMs, TimeUnit.MILLISECONDS)) {
                        System.out.printf("charge order=%s ABANDONED: context canceled%n",
                                request.getOrderId());
                        responder.onError(Status.CANCELLED.asRuntimeException());
                        return;
                    }
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    responder.onError(Status.CANCELLED.asRuntimeException());
                    return;
                } finally {
                    Context.current().removeListener(listener);
                }
            }

            if (request.getAmountCents() <= 0) {
                // A malformed request IS an RPC error, and INVALID_ARGUMENT is the gRPC
                // equivalent of a 400. Contrast with the decline below.
                responder.onError(Status.INVALID_ARGUMENT
                        .withDescription("amount_cents must be positive, got "
                                + request.getAmountCents())
                        .asRuntimeException());
                return;
            }

            boolean declined = alwaysDecline || request.getAmountCents() > declineOverCents;

            // THE DESIGN DECISION IN THIS FILE.
            //
            // A declined card is not an RPC failure. The call succeeded: we asked the
            // provider, the provider said no, and that answer arrived intact. So this
            // returns OK with status DECLINED, and NOT Status.PERMISSION_DENIED.
            //
            // The distinction matters more than it looks. gRPC error codes are how the
            // *transport* reports trouble, and clients quite reasonably retry some of
            // them. Encode a business outcome as one and every retry policy in the
            // system starts re-attempting a decision that will never change — while a
            // genuinely retryable UNAVAILABLE becomes indistinguishable from "this card
            // is stolen".
            //
            // Business outcomes go in the response. Failures go in the status.
            ChargeResponse.Builder response = ChargeResponse.newBuilder()
                    .setPaymentId(UUID.randomUUID().toString());
            if (declined) {
                response.setStatus(ChargeStatus.CHARGE_STATUS_DECLINED)
                        .setDeclineReason("amount exceeds the approval limit of "
                                + declineOverCents + " cents");
            } else {
                response.setStatus(ChargeStatus.CHARGE_STATUS_APPROVED)
                        .setAuthCode("AUTH-" + token());
            }

            ChargeResponse built = response.build();
            if (!key.isEmpty()) {
                charges.put(key, built);
            }

            System.out.printf("charge order=%s amount=%d status=%s%n", request.getOrderId(),
                    request.getAmountCents(), built.getStatus());
            responder.onNext(built);
            responder.onCompleted();
        }

        /**
         * Server streaming, declared in the contract and deliberately not built — see the
         * note in contracts/proto/bootcamp/payments/v1/payments.proto.
         *
         * <p>UNIMPLEMENTED is a defined, catchable answer meaning "this exists in the
         * contract and not yet in this deployment". That is a far better thing for a
         * consuming team to receive than a method that hangs or returns an empty stream,
         * and it is what lets a contract legitimately run ahead of its implementations.
         */
        @Override
        public void watchStatus(WatchStatusRequest request,
                                StreamObserver<PaymentStatus> responder) {
            responder.onError(Status.UNIMPLEMENTED
                    .withDescription("WatchStatus is declared in payments.v1 but not "
                            + "implemented in this deployment")
                    .asRuntimeException());
        }

        /** An 8-character uppercase authorisation token. */
        private static String token() {
            byte[] bytes = new byte[4];
            RANDOM.nextBytes(bytes);
            return HexFormat.of().withUpperCase().formatHex(bytes);
        }
    }
}
