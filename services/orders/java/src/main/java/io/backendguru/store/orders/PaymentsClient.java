package io.backendguru.store.orders;

import java.util.concurrent.TimeUnit;

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
 * SOLUTION — exercises 3.1, 3.2 and 3.3.
 *
 * <p>Compare with the same file on {@code main}:
 * {@code git diff main solution -- services/orders/java}
 *
 * <p>Three things arrived, in the order they matter. A deadline, so a slow payments
 * service cannot hold a checkout open forever. A bounded retry, legal only because
 * {@code Charge} carries an idempotency key. And a breaker, so that once payments is
 * clearly unwell we stop asking — which fails fast for us and takes load off it.
 *
 * <p>The first of those is worth more than the other two together. Delete the retry and
 * the breaker and this service still degrades honestly; delete the deadline and nothing
 * else here can save it.
 */
@Component
public class PaymentsClient {

    private static final Logger log = LoggerFactory.getLogger(PaymentsClient.class);

    /** Backoff between attempts. Never zero — an instant retry is just a second failure. */
    private static final long[] BACKOFF_MS = {50, 200, 800};

    private final ManagedChannel channel;
    private final PaymentsGrpc.PaymentsBlockingStub stub;
    private final long timeoutMs;
    private final int retryMax;
    private final int failureThreshold;
    private final long resetMs;

    // --- circuit breaker state (exercise 3.3) --------------------------------
    //
    // Guarded by `breakerLock`, because every HTTP request runs on its own thread and
    // an unsynchronised counter under concurrency is a bug that only shows up under
    // load — which is the only time this code matters.
    private final Object breakerLock = new Object();
    private int consecutiveFailures = 0;
    private long openedAtMs = 0;

    PaymentsClient(@Value("${store.payments.addr}") String address,
                   @Value("${store.payments.timeout-ms}") long timeoutMs,
                   @Value("${store.payments.retry-max}") int retryMax,
                   @Value("${store.breaker.failure-threshold}") int failureThreshold,
                   @Value("${store.breaker.reset-ms}") long resetMs) {
        this.timeoutMs = timeoutMs;
        this.retryMax = retryMax;
        this.failureThreshold = failureThreshold;
        this.resetMs = resetMs;

        this.channel = ManagedChannelBuilder.forTarget(address).usePlaintext().build();
        this.stub = PaymentsGrpc.newBlockingStub(channel);

        log.info("payments client -> {} (timeout {} ms, retries {}, breaker {}/{} ms)",
                address, timeoutMs, retryMax, failureThreshold, resetMs);
    }

    public ChargeOutcome charge(String orderId, long amountCents, String idempotencyKey) {
        ChargeRequest request = ChargeRequest.newBuilder()
                .setOrderId(orderId)
                .setAmountCents(amountCents)
                .setCurrency("EUR")
                .setIdempotencyKey(idempotencyKey)
                .build();

        // ================================================================
        // EXERCISE 3.3 — the breaker, checked before anything else.
        //
        // If payments has failed `failureThreshold` times in a row we do not call it at
        // all. That is not pessimism, it is arithmetic: the next call will almost
        // certainly fail too, and it would cost us `timeoutMs` per attempt to find out
        // while adding load to a service that is already struggling.
        // ================================================================
        if (breakerIsOpen()) {
            log.warn("order={} charge SKIPPED: circuit breaker is open", orderId);
            throw DomainException.paymentsUnavailable(
                    "The payment service is not answering, so we stopped calling it. "
                            + "No charge was made.");
        }

        Status.Code lastCode = null;

        // ================================================================
        // EXERCISE 3.2 — a BOUNDED retry.
        //
        // At most retryMax extra attempts, and only for the two codes that mean "try
        // again": UNAVAILABLE (nobody answered) and DEADLINE_EXCEEDED (somebody
        // answered too slowly). Never for a decline, which is not a failure, and never
        // for INVALID_ARGUMENT, which is our bug and will be our bug again next time.
        //
        // This is only legal because ChargeRequest carries an idempotency key and
        // payments returns the original response for a key it has seen. Take that away
        // and this loop bills the customer up to three times.
        // ================================================================
        for (int attempt = 0; attempt <= retryMax; attempt++) {
            try {
                // ========================================================
                // EXERCISE 3.1 — THE DEADLINE. The most important line in this file.
                //
                // withDeadlineAfter returns a NEW stub, so this is per call, not per
                // client — set it once in the constructor and you get a countdown that
                // starts at boot, expires, and never resets.
                //
                // The deadline is PER ATTEMPT, which means the worst case is
                // retryMax + 1 attempts plus backoff: with the defaults, 3 x 2000 ms +
                // 250 ms ~ 6.25 s. State that number out loud, because whoever calls
                // checkout has their own budget and 6 seconds may already be over it.
                //
                // The other defensible design is one deadline shared by all attempts —
                // compute the instant once, outside the loop. That keeps the promise at
                // 2 s but means a slow dependency eats the whole budget on attempt one
                // and the retries never happen. Which is the honest lesson underneath:
                // retries fix TRANSIENT failures, not slow ones.
                // ========================================================
                ChargeResponse response = stub
                        .withDeadlineAfter(timeoutMs, TimeUnit.MILLISECONDS)
                        .charge(request);

                recordSuccess();

                // A DECLINE IS NOT A FAILURE. The call succeeded; the answer was "no".
                // It does not count against the breaker and it is never retried.
                if (response.getStatus() == ChargeStatus.CHARGE_STATUS_DECLINED) {
                    log.info("order={} charge DECLINED: {}", orderId, response.getDeclineReason());
                    throw DomainException.paymentDeclined(
                            response.getDeclineReason().isEmpty()
                                    ? "The card was declined."
                                    : response.getDeclineReason());
                }

                log.info("order={} charge APPROVED auth={} (attempt {})",
                        orderId, response.getAuthCode(), attempt + 1);
                return new ChargeOutcome("APPROVED", response.getAuthCode());

            } catch (StatusRuntimeException transportFailure) {
                Status.Code code = transportFailure.getStatus().getCode();

                if (code != Status.Code.UNAVAILABLE && code != Status.Code.DEADLINE_EXCEEDED) {
                    // Not retryable, and not the breaker's business either: we sent
                    // something wrong and sending it again will not help.
                    throw new IllegalStateException(
                            "payments rejected the request: " + code, transportFailure);
                }

                lastCode = code;
                recordFailure();
                log.warn("order={} charge attempt {}/{} failed: {}",
                        orderId, attempt + 1, retryMax + 1, code);

                if (attempt < retryMax) {
                    sleep(BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]);
                }
            }
        }

        // Out of attempts. NO CHARGE WAS MADE — or if one was, the idempotency key means
        // a later retry finds it rather than duplicating it. 503 with Retry-After,
        // because the customer did nothing wrong.
        throw DomainException.paymentsUnavailable(
                "The payment service did not respond (%s) after %d attempts of %d ms. "
                        .formatted(lastCode, retryMax + 1, timeoutMs)
                        + "No charge was made.");
    }

    // --- the breaker ---------------------------------------------------------

    /**
     * Closed, open, or half-open.
     *
     * <p>Half-open is the state people forget, and leaving it out is worse than having
     * no breaker at all: a breaker that never closes again is a permanent outage you
     * built yourself. After {@code resetMs} this lets exactly one request through; if it
     * succeeds the breaker closes, and if it fails the clock restarts.
     */
    private boolean breakerIsOpen() {
        synchronized (breakerLock) {
            if (openedAtMs == 0) {
                return false;                                    // closed
            }
            if (System.currentTimeMillis() - openedAtMs >= resetMs) {
                log.info("circuit breaker HALF-OPEN: letting one probe through");
                openedAtMs = 0;                                  // half-open
                return false;
            }
            return true;                                         // open
        }
    }

    private void recordSuccess() {
        synchronized (breakerLock) {
            if (consecutiveFailures > 0) {
                log.info("circuit breaker CLOSED after a success");
            }
            consecutiveFailures = 0;
            openedAtMs = 0;
        }
    }

    private void recordFailure() {
        synchronized (breakerLock) {
            consecutiveFailures++;
            if (consecutiveFailures >= failureThreshold && openedAtMs == 0) {
                openedAtMs = System.currentTimeMillis();
                log.warn("circuit breaker OPEN after {} consecutive failures; "
                        + "not calling payments for {} ms", consecutiveFailures, resetMs);
            }
        }
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
    }

    @PreDestroy
    void shutdown() {
        channel.shutdown();
    }
}
