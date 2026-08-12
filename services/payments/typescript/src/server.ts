/**
 * PAYMENTS — a gRPC service, and the only one in the system with no HTTP surface and no
 * database.
 *
 * Nothing outside the store ever calls it, which is why it does not need REST: there is
 * no browser to please, no cache to negotiate with, and no human reading its responses.
 * What it does need is a contract that cannot drift and a wire format that is cheap on a
 * hot path, and that is the case for gRPC in one sentence.
 *
 * Note that there is no NestJS here, unlike catalog and orders. This service has no HTTP
 * surface, no controllers and nothing to inject; it is a file that starts a gRPC server.
 * Carrying a framework anyway would be carrying it for the sake of consistency, which is
 * not a reason.
 */

import { randomBytes, randomUUID } from 'node:crypto';
import {
  Server, ServerCredentials, ServerUnaryCall, sendUnaryData, status,
} from '@grpc/grpc-js';
import { HealthImplementation } from 'grpc-health-check';
import {
  ChargeRequest, ChargeResponse, ChargeStatus, PaymentsService,
} from './gen/bootcamp/payments/v1/payments';

const IMPLEMENTATION = 'typescript';

const PORT = process.env.PORT ?? '50051';
const DECLINE_OVER_CENTS = Number(process.env.PAYMENT_DECLINE_OVER_CENTS ?? 500_000);
const ALWAYS_DECLINE = process.env.PAYMENT_ALWAYS_DECLINE === 'true';
// The exercise dial. Set it above the caller's deadline and payments stops being down
// and starts being SLOW — which is the failure that actually hurts, because a slow
// service accepts your connection and then holds it.
const LATENCY_MS = Number(process.env.PAYMENT_LATENCY_MS ?? 0);

/**
 * Idempotency, in memory.
 *
 * A restart forgets every key, and that is a real limitation left visible rather than
 * hidden. In production this is a datastore with a TTL, and "where do idempotency
 * records live, and for how long" is a design question with real answers. Here it is a
 * Map, so you can see the shape of the idea.
 *
 * No lock, and for once that is not an oversight: Node runs this on one thread, so
 * nothing between the `get` and the `set` below can be interleaved. The same code in
 * Java, Python, Go, C# or Ruby needs a mutex.
 */
const charges = new Map<string, ChargeResponse>();

/** Unary: one request, one reply. */
function charge(
  call: ServerUnaryCall<ChargeRequest, ChargeResponse>,
  callback: sendUnaryData<ChargeResponse>,
): void {
  const request = call.request;

  // Idempotency first, before any work. A repeat of a key we have seen returns the
  // ORIGINAL answer and charges nothing — which is the entire reason the caller is
  // allowed to retry this method automatically.
  if (request.idempotencyKey) {
    const previous = charges.get(request.idempotencyKey);
    if (previous) {
      console.log(`charge order=${request.orderId} ` +
        `idempotency_key=${request.idempotencyKey} REPLAYED`);
      callback(null, previous);
      return;
    }
  }

  // Injected latency, applied while still watching whether the caller is still there.
  // If the caller gave up, so do we — continuing to work for a client that has stopped
  // listening is how an overloaded system stays overloaded.
  //
  // grpc-js signals that with a `cancelled` event on the call, which fires for a client
  // cancellation and for an expired deadline alike. This is Node's version of Go's
  // `select { case <-time.After(d): case <-ctx.Done(): }`, and the shape being the same
  // in six languages is not a coincidence: it is the same idea.
  if (LATENCY_MS > 0) {
    let abandoned = false;
    const onCancelled = () => {
      abandoned = true;
      console.log(`charge order=${request.orderId} ABANDONED: context canceled`);
    };
    call.on('cancelled', onCancelled);

    setTimeout(() => {
      call.removeListener('cancelled', onCancelled);
      if (abandoned) return;
      settle(request, callback);
    }, LATENCY_MS);
    return;
  }

  settle(request, callback);
}

function settle(
  request: ChargeRequest,
  callback: sendUnaryData<ChargeResponse>,
): void {
  if (request.amountCents <= 0) {
    // A malformed request IS an RPC error, and INVALID_ARGUMENT is the gRPC equivalent
    // of a 400. Contrast with the decline below.
    callback({
      code: status.INVALID_ARGUMENT,
      details: `amount_cents must be positive, got ${request.amountCents}`,
    }, null);
    return;
  }

  const declined = ALWAYS_DECLINE || request.amountCents > DECLINE_OVER_CENTS;

  // THE DESIGN DECISION IN THIS FILE.
  //
  // A declined card is not an RPC failure. The call succeeded: we asked the provider,
  // the provider said no, and that answer arrived intact. So this returns OK with status
  // DECLINED, and NOT status.PERMISSION_DENIED.
  //
  // The distinction matters more than it looks. gRPC error codes are how the *transport*
  // reports trouble, and clients quite reasonably retry some of them. Encode a business
  // outcome as one and every retry policy in the system starts re-attempting a decision
  // that will never change — while a genuinely retryable UNAVAILABLE becomes
  // indistinguishable from "this card is stolen".
  //
  // Business outcomes go in the response. Failures go in the status.
  const response: ChargeResponse = {
    paymentId: randomUUID(),
    status: declined ? ChargeStatus.CHARGE_STATUS_DECLINED : ChargeStatus.CHARGE_STATUS_APPROVED,
    authCode: declined ? '' : `AUTH-${randomBytes(4).toString('hex').toUpperCase()}`,
    declineReason: declined
      ? `amount exceeds the approval limit of ${DECLINE_OVER_CENTS} cents`
      : '',
  };

  if (request.idempotencyKey) {
    charges.set(request.idempotencyKey, response);
  }

  console.log(`charge order=${request.orderId} amount=${request.amountCents} ` +
    `status=${ChargeStatus[response.status]}`);
  callback(null, response);
}

/**
 * Server streaming, declared in the contract and deliberately not built — see the note
 * in contracts/proto/bootcamp/payments/v1/payments.proto.
 *
 * UNIMPLEMENTED is a defined, catchable answer meaning "this exists in the contract and
 * not yet in this deployment". That is a far better thing for a consuming team to
 * receive than a method that hangs or returns an empty stream, and it is what lets a
 * contract legitimately run ahead of its implementations.
 */
function watchStatus(call: any): void {
  call.emit('error', {
    code: status.UNIMPLEMENTED,
    details: 'WatchStatus is declared in payments.v1 but not implemented in this deployment',
  });
}

const server = new Server();
server.addService(PaymentsService, { charge, watchStatus });

// The standard gRPC health service. gRPC has its own health-checking protocol rather
// than borrowing HTTP's, so orchestrators probe it the same way in every language.
// Liveness only, same rule as the REST services: it reports on this process, never on
// its dependencies.
new HealthImplementation({ '': 'SERVING' }).addToServer(server);

server.bindAsync(`0.0.0.0:${PORT}`, ServerCredentials.createInsecure(), (error) => {
  if (error) {
    console.error(error);
    process.exit(1);
  }
  console.log(`payments (${IMPLEMENTATION}) listening on :${PORT}  ` +
    `decline_over=${DECLINE_OVER_CENTS} latency=${LATENCY_MS}ms`);
});
