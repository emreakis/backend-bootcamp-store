package io.backendguru.store;

/**
 * Domain outcomes, not accidents.
 *
 * <p>Every factory method below names a thing the business decided can happen. They
 * are thrown deep inside a module and translated to HTTP exactly once, at the edge,
 * by {@link ProblemAdvice}.
 *
 * <p>That translation is the whole discipline: a missing product must leave this
 * process as a designed 404, never as a stack trace. An API that only documents its
 * successes is half designed.
 *
 * <p>It extends {@code RuntimeException} deliberately. Spring only rolls a
 * transaction back on unchecked exceptions by default, and every one of these
 * <em>must</em> roll back the checkout it interrupted.
 */
public class DomainException extends RuntimeException {

    private final String kind;
    private final String title;
    private final int status;

    private DomainException(String kind, String title, int status, String detail) {
        super(detail);
        this.kind = kind;
        this.title = title;
        this.status = status;
    }

    public String kind() { return kind; }
    public String title() { return title; }
    public int status() { return status; }

    public static DomainException validationFailed(String detail) {
        return new DomainException("validation-failed", "Validation failed", 400, detail);
    }

    public static DomainException productNotFound(String sku) {
        return new DomainException("product-not-found", "Product not found", 404,
                "No product with sku '%s'.".formatted(sku));
    }

    public static DomainException insufficientStock(String sku, long requested, long available) {
        return new DomainException("insufficient-stock", "Insufficient stock", 409,
                "Product '%s' has %d in stock, %d requested.".formatted(sku, available, requested));
    }

    public static DomainException orderNotFound(String id) {
        return new DomainException("order-not-found", "Order not found", 404,
                "No order with id '%s'.".formatted(id));
    }

    /**
     * A state conflict — not a bad request, and not a server bug. This is what 409 is
     * for, and it is the status code most APIs forget to use.
     */
    public static DomainException orderNotCancellable(String id, String status) {
        return new DomainException("order-not-cancellable", "Order not cancellable", 409,
                "Order '%s' is %s and cannot be cancelled.".formatted(id, status));
    }

    public static DomainException paymentDeclined(String detail) {
        return new DomainException("payment-declined", "Payment declined", 402, detail);
    }
}
