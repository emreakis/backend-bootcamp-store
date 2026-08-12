/**
 * Domain outcomes, not accidents.
 *
 * Two of these did not exist in the monolith, and their arrival is the whole story of
 * this session: `CatalogUnavailable` and `PaymentsUnavailable`. In one process, a
 * module could not be down while its caller was up. Now it can, and the store owes its
 * customers an honest answer when it happens.
 *
 * Note which failures are 4xx and which are 5xx, because the split is a blame
 * assignment. A declined card is 402: the caller must change something (their card),
 * and retrying identically will never help. A dependency being unreachable is 503: the
 * caller did nothing wrong, should not change the request, and should come back later
 * — which is what `retryAfterSeconds` tells them.
 */

export class DomainError extends Error {
  constructor(
    readonly kind: string,
    readonly title: string,
    readonly status: number,
    readonly detail: string,
    readonly retryAfterSeconds?: number,
  ) {
    super(detail);
  }
}

export class ValidationFailed extends DomainError {
  constructor(detail: string) {
    super('validation-failed', 'Validation failed', 400, detail);
  }
}

/**
 * Catalog answered 404. Orders turns that into a designed order rejection rather than
 * passing a dependency's status through blindly or letting it become a 500.
 * Translating a dependency's vocabulary into your own is most of what an orchestrator
 * is for.
 */
export class ProductNotFound extends DomainError {
  constructor(sku: string) {
    super('product-not-found', 'Product not found', 404, `No product with sku '${sku}'.`);
  }
}

export class OrderNotFound extends DomainError {
  constructor(id: string) {
    super('order-not-found', 'Order not found', 404, `No order with id '${id}'.`);
  }
}

/** A state conflict — well-formed request, healthy server, impossible transition. */
export class OrderNotCancellable extends DomainError {
  constructor(id: string, status: string) {
    super('order-not-cancellable', 'Order not cancellable', 409,
      `Order '${id}' is ${status} and cannot be cancelled.`);
  }
}

export class PaymentDeclined extends DomainError {
  constructor(detail: string) {
    super('payment-declined', 'Payment declined', 402, detail);
  }
}

export class CatalogUnavailable extends DomainError {
  constructor(detail: string) {
    super('catalog-unavailable', 'Catalog unavailable', 503, detail, 5);
  }
}

/**
 * The response the Session 3 exercise exists to produce.
 *
 * Getting a fast, honest 503 out of a payments outage is something you build. The
 * default behaviour — no deadline, no breaker — is not this. It is every checkout
 * request piling onto an event loop waiting for a promise that never settles.
 */
export class PaymentsUnavailable extends DomainError {
  constructor(detail: string) {
    super('payments-unavailable', 'Payments unavailable', 503, detail, 5);
  }
}
