package io.backendguru.store.orders;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import io.backendguru.store.payments.v1.ChargeRequest;
import io.backendguru.store.payments.v1.ChargeResponse;
import io.backendguru.store.payments.v1.ChargeStatus;
import io.backendguru.store.payments.v1.PaymentsGrpc;
import io.grpc.ManagedChannel;
import io.grpc.ManagedChannelBuilder;
import io.grpc.Status;
import io.grpc.StatusRuntimeException;
import jakarta.annotation.PreDestroy;

/**
 * THE FILE THE SESSION 3 EXERCISE LIVES IN.
 *
 * <p>The gRPC half of this service's dependencies, and the one that will take the
 * store down with it if you let it. Everything below the constructor is the shape of
 * a remote call that has not yet been made safe.
 *
 * <p>Try it. Both of these hang, and neither of them should:
 *
 * <pre>
 *   docker compose stop payments                              # payments is DOWN
 *   PAYMENT_LATENCY_MS=30000 docker compose up -d payments    # payments is SLOW
 * </pre>
 *
 * <p>The first one surprises people. Surely a stopped server refuses connections and
 * the call fails at once? Not on a container network: nothing is listening, the SYN
 * packets are dropped rather than refused, and the connection attempt waits for a TCP
 * timeout measured in minutes. "Down" and "slow" are the same thing to a caller with
 * no deadline — which is why the deadline, not the outage, is the thing to fix.
 *
 * <p>Meanwhile {@code GET /health} on this service keeps answering 200, because orders
 * is not sick. Its dependency is. Watching a completely healthy service become
 * unusable anyway is the moment Session 3 exists for, and it is the fallacy from
 * Session 1 — <em>the network is reliable</em> — collecting its debt.
 */
@Component
public class PaymentsClient {

    private static final Logger log = LoggerFactory.getLogger(PaymentsClient.class);

    private final ManagedChannel channel;
    private final PaymentsGrpc.PaymentsBlockingStub stub;
    private final long timeoutMs;
    private final int retryMax;

    PaymentsClient(@Value("${store.payments.addr}") String address,
                   @Value("${store.payments.timeout-ms}") long timeoutMs,
                   @Value("${store.payments.retry-max}") int retryMax) {
        this.timeoutMs = timeoutMs;
        this.retryMax = retryMax;

        // The channel is built once and reused for the life of the process.
        //
        // It is not a connection. It is a managed thing that resolves the name, opens
        // connections as needed, multiplexes concurrent calls over HTTP/2 and
        // reconnects on its own after a failure. Building one per request is both
        // slow and a misunderstanding of what it is.
        //
        // `payments` is not a hostname anybody configured — it is a service name the
        // platform resolves. Plaintext because this hop is inside the cluster; in
        // production a service that moves money gets mTLS.
        this.channel = ManagedChannelBuilder.forTarget(address).usePlaintext().build();
        this.stub = PaymentsGrpc.newBlockingStub(channel);

        log.info("payments client -> {} (timeout {} ms, retries {})", address, timeoutMs, retryMax);
    }

    /**
     * Charge the card.
     *
     * @param idempotencyKey the order id, which makes this call safe to repeat — and
     *                       is therefore the precondition for exercise 3.2. Retrying a
     *                       charge without one bills the customer twice.
     */
    public ChargeOutcome charge(String orderId, long amountCents, String idempotencyKey) {
        ChargeRequest request = ChargeRequest.newBuilder()
                .setOrderId(orderId)
                .setAmountCents(amountCents)
                .setCurrency("EUR")
                .setIdempotencyKey(idempotencyKey)
                .build();

        try {
            // ================================================================
            // TODO (exercise 3.1) — GIVE THIS CALL A DEADLINE.       [do this first]
            //
            // `stub.charge(request)` waits forever. Not "a long time" — forever. The
            // default value of a missing deadline is the worst value it could have,
            // and it is the single most important line missing from this file.
            //
            // Every gRPC stub takes one, in every language:
            //
            //     stub.withDeadlineAfter(timeoutMs, TimeUnit.MILLISECONDS).charge(request)
            //
            // Note it returns a NEW stub — the deadline is per call, not per client,
            // so assigning it back to `this.stub` in the constructor would start a
            // countdown at boot that expires once and never resets.
            //
            // The deadline also travels: payments sees the caller's remaining budget
            // and abandons its own work when the budget runs out, instead of
            // finishing an answer nobody is listening for.
            //
            // Verify: PAYMENT_LATENCY_MS=30000, then POST an order. Before, it hangs;
            // after, you get a 503 in two seconds.
            // ================================================================

            // ================================================================
            // TODO (exercise 3.2) — RETRY, BUT ONLY BECAUSE YOU MAY.       [then this]
            //
            // Wrap the call in a bounded retry: at most `retryMax` extra attempts,
            // with backoff between them (say 50 ms, then 200 ms), and ONLY for
            // Status.UNAVAILABLE and Status.DEADLINE_EXCEEDED.
            //
            // Three rules, each of which someone learns the hard way:
            //
            //   1. Only retry what is safe to repeat. This call is, because
            //      ChargeRequest carries an idempotency key and payments returns the
            //      original response for a key it has seen. Delete that field and
            //      this exercise becomes a double-billing bug.
            //
            //   2. Never retry a business outcome. A declined card will be declined
            //      again; retrying it just costs the customer time.
            //
            //   3. Bound it, and back off. Retrying into an overloaded service is how
            //      a brownout becomes an outage — you add load to the exact system
            //      that is failing from load. Three attempts and a budget, not "retry
            //      until success".
            // ================================================================

            // ================================================================
            // TODO (exercise 3.3) — PUT A CIRCUIT BREAKER IN FRONT.        [last]
            //
            // Count consecutive failures. At `store.breaker.failure-threshold`, stop
            // calling payments at all and fail immediately for
            // `store.breaker.reset-ms`; then let one probe through and close on
            // success.
            //
            // A breaker does two jobs, and the second is the one people forget:
            //
            //   * it turns a slow hang into an instant, designed failure, so orders
            //     stops burning threads on a call it can predict will fail; and
            //   * it takes load OFF payments, giving it room to recover. Without one,
            //     a struggling service is held under by the traffic of everyone
            //     politely waiting for it.
            //
            // Resilience4j does this properly and is worth reaching for in real code.
            // Writing the twenty lines yourself once is worth doing first, because
            // then you know what it is doing.
            // ================================================================

            ChargeResponse response = stub.charge(request);

            // A DECLINE IS NOT A FAILURE. The call succeeded; the answer was "no".
            //
            // Payments deliberately returns OK with status DECLINED rather than a gRPC
            // error code, so that no retry policy in the system ever re-attempts a
            // decision that will never change. Here that becomes a 402 — the
            // customer's problem to solve, and not ours.
            if (response.getStatus() == ChargeStatus.CHARGE_STATUS_DECLINED) {
                log.info("order={} charge DECLINED: {}", orderId, response.getDeclineReason());
                throw DomainException.paymentDeclined(
                        response.getDeclineReason().isEmpty()
                                ? "The card was declined."
                                : response.getDeclineReason());
            }

            log.info("order={} charge APPROVED auth={}", orderId, response.getAuthCode());
            return new ChargeOutcome("APPROVED", response.getAuthCode());

        } catch (StatusRuntimeException transportFailure) {
            Status.Code code = transportFailure.getStatus().getCode();
            log.warn("order={} charge failed at the transport: {}", orderId, code);

            // Transport-level trouble. The customer did nothing wrong, so this is a
            // 5xx and carries Retry-After. Crucially, NO CHARGE WAS MADE — or if one
            // was, the idempotency key means the retry will find it rather than
            // duplicate it.
            if (code == Status.Code.UNAVAILABLE || code == Status.Code.DEADLINE_EXCEEDED) {
                throw DomainException.paymentsUnavailable(
                        "The payment service did not respond within %d ms. No charge was made."
                                .formatted(timeoutMs));
            }

            // Anything else — INVALID_ARGUMENT, UNIMPLEMENTED — means we sent
            // something wrong, which is our bug and not a retry candidate.
            throw new IllegalStateException("payments rejected the request: " + code, transportFailure);
        }
    }

    @PreDestroy
    void shutdown() {
        channel.shutdown();
    }
}
