/**
 * Domain outcomes, not accidents.
 *
 * Every class below names a thing the business decided can happen. They are thrown
 * deep inside a module and translated to HTTP exactly once, at the edge, by
 * ProblemFilter.
 *
 * That translation is the whole discipline: a missing product must leave this
 * process as a designed 404, never as a stack trace. An API that only documents its
 * successes is half designed.
 */

export class DomainError extends Error {
  constructor(
    readonly kind: string,
    readonly title: string,
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
  }
}

export class ValidationFailed extends DomainError {
  constructor(detail: string) {
    super('validation-failed', 'Validation failed', 400, detail);
  }
}

export class ProductNotFound extends DomainError {
  constructor(sku: string) {
    super('product-not-found', 'Product not found', 404, `No product with sku '${sku}'.`);
  }
}

export class InsufficientStock extends DomainError {
  constructor(sku: string, requested: number, available: number) {
    super('insufficient-stock', 'Insufficient stock', 409,
      `Product '${sku}' has ${available} in stock, ${requested} requested.`);
  }
}

export class OrderNotFound extends DomainError {
  constructor(id: string) {
    super('order-not-found', 'Order not found', 404, `No order with id '${id}'.`);
  }
}

/**
 * A state conflict — not a bad request, and not a server bug. This is what 409 is
 * for, and it is the status code most APIs forget to use.
 */
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
