package io.backendguru.store.orders;

/**
 * Domain outcomes, not accidents.
 *
 * <p>Two of these did not exist in the monolith, and their arrival is the whole story
 * of this session: {@link #catalogUnavailable} and {@link #paymentsUnavailable}. In one
 * process, a module could not be down while its caller was up. Now it can, and the
 * store owes its customers an honest answer when it happens.
 *
 * <p>Note which failures are 4xx and which are 5xx, because the split is a blame
 * assignment. A declined card is 402: the caller must change something (their card),
 * and retrying identically will never help. A dependency being unreachable is 503: the
 * caller did nothing wrong, should not change the request, and should come back later
 * — which is what {@code retryAfterSeconds} tells them.
 */
public class DomainException extends RuntimeException {

    private final String kind;
    private final String title;
    private final int status;
    private final Integer retryAfterSeconds;

    private DomainException(String kind, String title, int status, String detail,
                            Integer retryAfterSeconds) {
        super(detail);
        this.kind = kind;
        this.title = title;
        this.status = status;
        this.retryAfterSeconds = retryAfterSeconds;
    }

    public String kind() { return kind; }
    public String title() { return title; }
    public int status() { return status; }
    public Integer retryAfterSeconds() { return retryAfterSeconds; }

    public static DomainException validationFailed(String detail) {
        return new DomainException("validation-failed", "Validation failed", 400, detail, null);
    }

    /**
     * Catalog answered 404. Orders turns that into a designed order rejection rather
     * than passing a dependency's status through blindly or letting it become a 500.
     * Translating a dependency's vocabulary into your own is most of what an
     * orchestrator is for.
     */
    public static DomainException productNotFound(String sku) {
        return new DomainException("product-not-found", "Product not found", 404,
                "No product with sku '%s'.".formatted(sku), null);
    }

    public static DomainException orderNotFound(String id) {
        return new DomainException("order-not-found", "Order not found", 404,
                "No order with id '%s'.".formatted(id), null);
    }

    /** A state conflict — well-formed request, healthy server, impossible transition. */
    public static DomainException orderNotCancellable(String id, String status) {
        return new DomainException("order-not-cancellable", "Order not cancellable", 409,
                "Order '%s' is %s and cannot be cancelled.".formatted(id, status), null);
    }

    public static DomainException paymentDeclined(String detail) {
        return new DomainException("payment-declined", "Payment declined", 402, detail, null);
    }

    public static DomainException catalogUnavailable(String detail) {
        return new DomainException("catalog-unavailable", "Catalog unavailable", 503, detail, 5);
    }

    /**
     * The response the Session 3 exercise exists to produce.
     *
     * <p>Getting a fast, honest 503 out of a payments outage is something you build.
     * The default behaviour — no deadline, no breaker — is not this. It is every
     * checkout thread blocking until the pool drains and the store goes down with its
     * dependency.
     */
    public static DomainException paymentsUnavailable(String detail) {
        return new DomainException("payments-unavailable", "Payments unavailable", 503, detail, 5);
    }
}
