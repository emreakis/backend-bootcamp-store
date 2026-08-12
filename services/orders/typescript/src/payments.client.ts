/**
 * SOLUTION — exercises 3.1, 3.2 and 3.3.
 *
 * Compare with the same file on `main`:
 *
 *     git diff main solution -- services/orders/typescript
 *
 * Three things arrived, in the order they matter. A deadline, so a slow payments service
 * cannot hold a checkout open forever. A bounded retry, legal only because `Charge`
 * carries an idempotency key. And a breaker, so that once payments is clearly unwell we
 * stop asking — which fails fast for us and takes load off it.
 *
 * The first of those is worth more than the other two together. Delete the retry and the
 * breaker and this service still degrades honestly; delete the deadline and nothing else
 * here can save it.
 */

import { Injectable, Logger, OnModuleDestroy } from '@nestjs/common';
import { CallOptions, ChannelCredentials, Metadata, ServiceError, status } from '@grpc/grpc-js';
import { config } from './config';
import { PaymentDeclined, PaymentsUnavailable } from './errors';
import type { Payment } from './model';
import {
  ChargeRequest,
  ChargeResponse,
  ChargeStatus,
  PaymentsClient as GeneratedPaymentsClient,
} from './gen/bootcamp/payments/v1/payments';

/** Backoff between attempts. Never zero — an instant retry is just a second failure. */
const BACKOFF_MS = [50, 200, 800];

/** The two codes that mean "try again": nobody answered, or somebody answered too slowly. */
const RETRYABLE: number[] = [status.UNAVAILABLE, status.DEADLINE_EXCEEDED];

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Exercise 3.3 — closed, open, or half-open.
 *
 * Half-open is the state people forget, and leaving it out is worse than having no
 * breaker at all: a breaker that never closes again is a permanent outage you built
 * yourself. After `resetMs` this lets exactly one request through; if it succeeds the
 * breaker closes, and if it fails the clock restarts.
 *
 * No lock, and for once that is not an oversight: Node runs this on one thread, so
 * nothing can interleave between reading and writing these fields. The same twenty
 * lines in Java, Python, Go, C# or Ruby need a mutex. Worth noticing, because the
 * *failure* Node has instead is worse — no thread pool to exhaust means the symptom of
 * a hung dependency is memory quietly filling with pending promises while the process
 * still reports itself healthy.
 */
class CircuitBreaker {
  private readonly logger = new Logger(CircuitBreaker.name);
  private consecutiveFailures = 0;
  private openedAt: number | null = null;

  constructor(private readonly threshold: number, private readonly resetMs: number) {}

  isOpen(): boolean {
    if (this.openedAt === null) return false;                 // closed
    if (Date.now() - this.openedAt >= this.resetMs) {
      this.logger.log('circuit breaker HALF-OPEN: letting one probe through');
      this.openedAt = null;                                   // half-open
      return false;
    }
    return true;                                              // open
  }

  recordSuccess(): void {
    if (this.consecutiveFailures) {
      this.logger.log('circuit breaker CLOSED after a success');
    }
    this.consecutiveFailures = 0;
    this.openedAt = null;
  }

  recordFailure(): void {
    this.consecutiveFailures += 1;
    if (this.consecutiveFailures >= this.threshold && this.openedAt === null) {
      this.openedAt = Date.now();
      this.logger.warn(`circuit breaker OPEN after ${this.consecutiveFailures} ` +
        `consecutive failures; not calling payments for ${this.resetMs} ms`);
    }
  }
}

@Injectable()
export class PaymentsClient implements OnModuleDestroy {
  private readonly logger = new Logger(PaymentsClient.name);
  private readonly client: GeneratedPaymentsClient;
  private readonly breaker = new CircuitBreaker(
    config.breakerFailureThreshold, config.breakerResetMs);

  constructor() {
    this.client = new GeneratedPaymentsClient(
      config.paymentsAddr, ChannelCredentials.createInsecure());

    this.logger.log(`payments client -> ${config.paymentsAddr} ` +
      `(timeout ${config.paymentsTimeoutMs} ms, retries ${config.paymentsRetryMax}, ` +
      `breaker ${config.breakerFailureThreshold}/${config.breakerResetMs} ms)`);
  }

  async charge(orderId: string, amountCents: number, idempotencyKey: string): Promise<Payment> {
    const request: ChargeRequest = {
      orderId,
      amountCents,
      currency: 'EUR',
      idempotencyKey,
    };

    // EXERCISE 3.3 — the breaker, checked before anything else.
    //
    // If payments has failed breakerFailureThreshold times in a row we do not call it at
    // all. That is not pessimism, it is arithmetic: the next call will almost certainly
    // fail too, and it would cost us the full timeout per attempt to find out while
    // adding load to a service that is already struggling.
    if (this.breaker.isOpen()) {
      this.logger.warn(`order=${orderId} charge SKIPPED: circuit breaker is open`);
      throw new PaymentsUnavailable(
        'The payment service is not answering, so we stopped calling it. No charge was made.');
    }

    let lastCode: number | undefined;

    // EXERCISE 3.2 — a BOUNDED retry.
    //
    // At most paymentsRetryMax extra attempts, and only for the two retryable codes.
    // Never for a decline, which is not a failure, and never for INVALID_ARGUMENT, which
    // is our bug and will be our bug again next time.
    //
    // This is only legal because ChargeRequest carries an idempotency key and payments
    // returns the original response for a key it has seen. Take that away and this loop
    // bills the customer up to three times.
    for (let attempt = 0; attempt <= config.paymentsRetryMax; attempt += 1) {
      // ================================================================
      // EXERCISE 3.1 — THE DEADLINE. The most important line in this file.
      //
      // grpc-js wants an ABSOLUTE point in time, not a duration — and computing it
      // INSIDE the loop is what makes the deadline per attempt.
      //
      // That is a real decision. Per attempt, the worst case is retries + 1 attempts
      // plus backoff: with the defaults, 3 x 2000 ms + 250 ms ~ 6.25 s. Hoist this one
      // line above the loop instead and all three attempts share a single 2 s budget —
      // the promise stays at 2 s, but a slow dependency eats the whole thing on attempt
      // one and the retries never happen.
      //
      // Which is the honest lesson underneath: retries fix TRANSIENT failures, not slow
      // ones. Node is the language that shows you the choice, because it is the one
      // that makes you write the instant down.
      // ================================================================
      const options: CallOptions = {
        deadline: Date.now() + config.paymentsTimeoutMs,
      };

      let response: ChargeResponse;
      try {
        response = await new Promise<ChargeResponse>((resolve, reject) => {
          this.client.charge(request, new Metadata(), options,
            (error: ServiceError | null, value: ChargeResponse) =>
              error ? reject(error) : resolve(value));
        });
      } catch (error) {
        const code = (error as ServiceError).code;

        if (!RETRYABLE.includes(code)) {
          // Not retryable, and not the breaker's business either: we sent something
          // wrong and sending it again will not help.
          throw new Error(`payments rejected the request: ${status[code]}`);
        }

        lastCode = code;
        this.breaker.recordFailure();
        this.logger.warn(`order=${orderId} charge attempt ${attempt + 1}/` +
          `${config.paymentsRetryMax + 1} failed: ${status[code]}`);

        if (attempt < config.paymentsRetryMax) {
          await sleep(BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]);
        }
        continue;
      }

      this.breaker.recordSuccess();

      // A DECLINE IS NOT A FAILURE. The call succeeded; the answer was "no". It does not
      // count against the breaker and it is never retried.
      if (response.status === ChargeStatus.CHARGE_STATUS_DECLINED) {
        this.logger.log(`order=${orderId} charge DECLINED: ${response.declineReason}`);
        throw new PaymentDeclined(response.declineReason || 'The card was declined.');
      }

      this.logger.log(`order=${orderId} charge APPROVED auth=${response.authCode} ` +
        `(attempt ${attempt + 1})`);
      return { status: 'APPROVED', auth_code: response.authCode };
    }

    // Out of attempts. NO CHARGE WAS MADE — or if one was, the idempotency key means a
    // later retry finds it rather than duplicating it. 503 with Retry-After, because the
    // customer did nothing wrong.
    throw new PaymentsUnavailable(
      `The payment service did not respond (${lastCode !== undefined ? status[lastCode] : 'unknown'}) ` +
      `after ${config.paymentsRetryMax + 1} attempts of ${config.paymentsTimeoutMs} ms. ` +
      'No charge was made.');
  }

  onModuleDestroy() {
    this.client.close();
  }
}
