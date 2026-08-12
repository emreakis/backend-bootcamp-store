namespace Store;

/// <summary>
/// Domain outcomes, not accidents.
///
/// Every factory method below names a thing the business decided can happen. They are
/// thrown deep inside a module and translated to HTTP exactly once, at the edge, by
/// the problem middleware in Program.cs.
///
/// That translation is the whole discipline: a missing product must leave this process
/// as a designed 404, never as a stack trace. An API that only documents its successes
/// is half designed.
/// </summary>
public sealed class DomainException(string kind, string title, int status, string detail)
    : Exception(detail)
{
    public string Kind { get; } = kind;
    public string Title { get; } = title;
    public int Status { get; } = status;
    public string Detail { get; } = detail;

    public static DomainException ValidationFailed(string detail) =>
        new("validation-failed", "Validation failed", 400, detail);

    public static DomainException ProductNotFound(string sku) =>
        new("product-not-found", "Product not found", 404, $"No product with sku '{sku}'.");

    public static DomainException InsufficientStock(string sku, long requested, long available) =>
        new("insufficient-stock", "Insufficient stock", 409,
            $"Product '{sku}' has {available} in stock, {requested} requested.");

    public static DomainException OrderNotFound(string id) =>
        new("order-not-found", "Order not found", 404, $"No order with id '{id}'.");

    /// <summary>
    /// A state conflict — not a bad request, and not a server bug. This is what 409 is
    /// for, and it is the status code most APIs forget to use.
    /// </summary>
    public static DomainException OrderNotCancellable(string id, string status) =>
        new("order-not-cancellable", "Order not cancellable", 409,
            $"Order '{id}' is {status} and cannot be cancelled.");

    public static DomainException PaymentDeclined(string detail) =>
        new("payment-declined", "Payment declined", 402, detail);
}
