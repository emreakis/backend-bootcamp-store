/**
 * THE FILE THE SESSION 3 EXERCISE LIVES IN.
 *
 * The gRPC half of this service's dependencies, and the one that will take the store
 * down with it if you let it. Everything inside `charge` is the shape of a remote call
 * that has not yet been made safe.
 *
 * Try it. All three of these break payments, and they do not break it the same way:
 *
 *     PAYMENT_LATENCY_MS=30000 docker compose up -d payments   # SLOW
 *     docker compose pause payments                            # BLACK HOLE
 *     docker compose stop payments                             # DOWN
 *
 * The first two hang, in every language, every time. A slow server accepts your
 * connection and then never answers; a PAUSED one keeps its address and takes your SYN
 * packets without acknowledging them, which is what a crashed host or a network
 * partition looks like from the outside.
 *
 * The third is the one that surprises people, because it is not one behaviour. A
 * stopped container loses its address and its DNS entry, and how long the failure
 * takes is decided by whichever gRPC library you happen to be using. Measured on this
 * stack, with no deadline anywhere: C# fails in about 4 seconds, Python, Go and Ruby
 * in about 20 (their own connect timeout), and Java and TypeScript were still waiting
 * after 25.
 *
 * Same outage, same contract, four seconds to never. THAT is the argument for the
 * deadline: without one, how long checkout hangs is a property of somebody else's
 * default rather than a number you chose — and 20 seconds is not "fast" for a
 * checkout, it is a hang with extra steps.
 *
 * Meanwhile `GET /health` on this service keeps answering 200, because orders is not
 * sick. Its dependency is. Watching a completely healthy service become unusable anyway
 * is the moment Session 3 exists for, and it is the fallacy from Session 1 — *the
 * network is reliable* — collecting its debt.
 *
 * There is no generated code in this repository. The Dockerfile runs protoc with
 * ts-proto over ../../../contracts/proto before `tsc` ever sees this file, so
 * `./gen/bootcamp/payments/v1/payments` below is the contract, compiled. Delete a
 * field from the .proto and this stops type-checking.
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

@Injectable()
export class PaymentsClient implements OnModuleDestroy {
  private readonly logger = new Logger(PaymentsClient.name);
  private readonly client: GeneratedPaymentsClient;

  constructor() {
    // The channel is built once and reused for the life of the process.
    //
    // It is not a connection. It is a managed thing that resolves the name, opens
    // connections as needed, multiplexes concurrent calls over HTTP/2 and reconnects
    // on its own after a failure. Building one per request is both slow and a
    // misunderstanding of what it is.
    //
    // `payments` is not a hostname anybody configured — it is a service name the
    // platform resolves. Insecure credentials because this hop is inside the cluster;
    // in production a service that moves money gets mTLS.
    this.client = new GeneratedPaymentsClient(
      config.paymentsAddr, ChannelCredentials.createInsecure());

    this.logger.log(`payments client -> ${config.paymentsAddr} ` +
      `(timeout ${config.paymentsTimeoutMs} ms, retries ${config.paymentsRetryMax})`);
  }

  /**
   * Charge the card.
   *
   * `idempotencyKey` is what makes this call safe to repeat, and is therefore the
   * precondition for exercise 3.2. Retrying a charge without one bills the customer
   * twice.
   */
  async charge(orderId: string, amountCents: number, idempotencyKey: string): Promise<Payment> {
    const request: ChargeRequest = {
      orderId,
      amountCents,
      currency: 'EUR',
      idempotencyKey,
    };

    const options: CallOptions = {
      // ================================================================
      // TODO (exercise 3.1) — GIVE THIS CALL A DEADLINE.       [do this first]
      //
      // These options are empty, so the call waits forever. Not "a long time" —
      // forever. The default value of a missing deadline is the worst value it could
      // have, and it is the single most important line missing from this file.
      //
      // grpc-js wants an ABSOLUTE point in time, not a duration:
      //
      //     deadline: Date.now() + config.paymentsTimeoutMs
      //
      // That is worth pausing on. Python takes `timeout=2.0`, Go takes
      // `context.WithTimeout(ctx, 2*time.Second)`, and both of those are durations
      // that the library immediately converts into an absolute instant. A deadline is
      // a moment — "be done by 10:42:03.500" — which is exactly what makes it
      // composable: the same instant can be handed to three nested calls and they
      // share one budget, whereas three nested two-second *timeouts* take six seconds.
      //
      // The deadline also travels: gRPC puts the remaining budget on the wire,
      // payments sees it and abandons its own work when the budget runs out instead
      // of finishing an answer nobody is listening for. Watch the payments log say
      // "ABANDONED: context canceled" the moment this expires.
      //
      // Verify: PAYMENT_LATENCY_MS=30000, then POST an order. Before, it hangs; after,
      // you get a 503 in two seconds.
      // ================================================================
    };

    // ================================================================
    // TODO (exercise 3.2) — RETRY, BUT ONLY BECAUSE YOU MAY.       [then this]
    //
    // Wrap the call below in a bounded retry: at most `config.paymentsRetryMax` extra
    // attempts, with backoff between them (say 50 ms, then 200 ms), and ONLY for
    // status.UNAVAILABLE and status.DEADLINE_EXCEEDED.
    //
    // Three rules, each of which someone learns the hard way:
    //
    //   1. Only retry what is safe to repeat. This call is, because ChargeRequest
    //      carries an idempotency key and payments returns the original response for a
    //      key it has seen. Delete that field and this exercise becomes a
    //      double-billing bug.
    //
    //   2. Never retry a business outcome. A declined card will be declined again;
    //      retrying it just costs the customer time.
    //
    //   3. Bound it, and back off. Retrying into an overloaded service is how a
    //      brownout becomes an outage — you add load to the exact system that is
    //      failing from load. Three attempts and a budget, not "retry until success".
    //
    // Note the interaction with 3.1: because a grpc-js deadline is an absolute
    // instant, computing it ONCE outside the retry loop gives all attempts a single
    // shared budget. Recomputing `Date.now() + timeout` inside the loop gives each
    // attempt its own, and turns a 2 s promise into a 6 s one. Both are defensible;
    // only one of them is what you meant.
    // ================================================================

    // ================================================================
    // TODO (exercise 3.3) — PUT A CIRCUIT BREAKER IN FRONT.        [last]
    //
    // Count consecutive failures. At `config.breakerFailureThreshold`, stop calling
    // payments at all and fail immediately for `config.breakerResetMs`; then let one
    // probe through and close on success.
    //
    // A breaker does two jobs, and the second is the one people forget:
    //
    //   * it turns a slow hang into an instant, designed failure, so orders stops
    //     accumulating pending promises on a call it can predict will fail; and
    //   * it takes load OFF payments, giving it room to recover. Without one, a
    //     struggling service is held under by the traffic of everyone politely
    //     waiting for it.
    //
    // Node's single-threaded event loop makes the counter easy — no locking, because
    // nothing here is pre-empted mid-update. It also makes the failure worse: there
    // is no thread pool to exhaust, so the symptom is not "the pool is full", it is
    // memory quietly filling with pending promises while the process still reports
    // itself healthy. `opossum` is the library; write the twenty lines yourself once
    // first, because then you know what it is doing.
    // ================================================================

    let response: ChargeResponse;
    try {
      response = await new Promise<ChargeResponse>((resolve, reject) => {
        // Four arguments, and the empty Metadata is not optional here: grpc-js has no
        // (request, options, callback) overload, so per-call options always arrive
        // behind a metadata object. Metadata is the gRPC equivalent of HTTP headers —
        // where a trace id or an auth token would go if this hop carried either.
        this.client.charge(request, new Metadata(), options,
          (error: ServiceError | null, value: ChargeResponse) =>
            error ? reject(error) : resolve(value));
      });
    } catch (error) {
      const code = (error as ServiceError).code;
      this.logger.warn(`order=${orderId} charge failed at the transport: ${status[code]}`);

      // Transport-level trouble. The customer did nothing wrong, so this is a 5xx and
      // carries Retry-After. Crucially, NO CHARGE WAS MADE — or if one was, the
      // idempotency key means the retry will find it rather than duplicate it.
      if (code === status.UNAVAILABLE || code === status.DEADLINE_EXCEEDED) {
        throw new PaymentsUnavailable(
          `The payment service did not respond within ${config.paymentsTimeoutMs} ms. ` +
          'No charge was made.');
      }

      // Anything else — INVALID_ARGUMENT, UNIMPLEMENTED — means we sent something
      // wrong, which is our bug and not a retry candidate.
      throw new Error(`payments rejected the request: ${status[code]}`);
    }

    // A DECLINE IS NOT A FAILURE. The call succeeded; the answer was "no".
    //
    // Payments deliberately returns OK with status DECLINED rather than a gRPC error
    // code, so that no retry policy in the system ever re-attempts a decision that will
    // never change. Here that becomes a 402 — the customer's problem to solve, and not
    // ours.
    if (response.status === ChargeStatus.CHARGE_STATUS_DECLINED) {
      this.logger.log(`order=${orderId} charge DECLINED: ${response.declineReason}`);
      throw new PaymentDeclined(response.declineReason || 'The card was declined.');
    }

    this.logger.log(`order=${orderId} charge APPROVED auth=${response.authCode}`);
    return { status: 'APPROVED', auth_code: response.authCode };
  }

  onModuleDestroy() {
    this.client.close();
  }
}
