namespace Orders;

/// <summary>
/// Domain outcomes, not accidents.
///
/// <para>Two of these did not exist in the monolith, and their arrival is the whole
/// story of this session: <see cref="CatalogUnavailable"/> and
/// <see cref="PaymentsUnavailable"/>. In one process, a module could not be down while
/// its caller was up. Now it can, and the store owes its customers an honest answer
/// when it happens.</para>
///
/// <para>Note which failures are 4xx and which are 5xx, because the split is a blame
/// assignment. A declined card is 402: the caller must change something (their card),
/// and retrying identically will never help. A dependency being unreachable is 503: the
/// caller did nothing wrong, should not change the request, and should come back later
/// — which is what <c>RetryAfterSeconds</c> tells them.</para>
/// </summary>
public class DomainException(string kind, string title, int status, string detail,
                             int? retryAfterSeconds = null) : Exception(detail)
{
    public string Kind { get; } = kind;
    public string Title { get; } = title;
    public int Status { get; } = status;
    public string Detail { get; } = detail;
    public int? RetryAfterSeconds { get; } = retryAfterSeconds;

    public static DomainException ValidationFailed(string detail) =>
        new("validation-failed", "Validation failed", 400, detail);

    /// <summary>
    /// Catalog answered 404. Orders turns that into a designed order rejection rather
    /// than passing a dependency's status through blindly or letting it become a 500.
    /// Translating a dependency's vocabulary into your own is most of what an
    /// orchestrator is for.
    /// </summary>
    public static DomainException ProductNotFound(string sku) =>
        new("product-not-found", "Product not found", 404, $"No product with sku '{sku}'.");

    public static DomainException OrderNotFound(string id) =>
        new("order-not-found", "Order not found", 404, $"No order with id '{id}'.");

    /// <summary>A state conflict — well-formed request, healthy server, impossible transition.</summary>
    public static DomainException OrderNotCancellable(string id, string status) =>
        new("order-not-cancellable", "Order not cancellable", 409,
            $"Order '{id}' is {status} and cannot be cancelled.");

    public static DomainException PaymentDeclined(string detail) =>
        new("payment-declined", "Payment declined", 402, detail);

    public static DomainException CatalogUnavailable(string detail) =>
        new("catalog-unavailable", "Catalog unavailable", 503, detail, 5);

    /// <summary>
    /// The response the Session 3 exercise exists to produce.
    ///
    /// <para>Getting a fast, honest 503 out of a payments outage is something you
    /// build. The default behaviour — no deadline, no breaker — is not this. It is
    /// every checkout request blocking until the thread pool starves and the store goes
    /// down with its dependency.</para>
    /// </summary>
    public static DomainException PaymentsUnavailable(string detail) =>
        new("payments-unavailable", "Payments unavailable", 503, detail, 5);
}

/// <summary>One error envelope, everywhere — RFC 9457, exactly as contracts/problem.yaml says.</summary>
public record Problem(string Type, string Title, int Status, string Detail, string Instance)
{
    public const string Base = "https://bootcamp.backendguru.io/problems/";

    public static Problem From(DomainException exception, string instance) =>
        new(Base + exception.Kind, exception.Title, exception.Status, exception.Detail, instance);
}
