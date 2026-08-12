namespace Orders;

// The shapes this service reads and writes.
//
// Every property is PascalCase, and every field on the wire is snake_case, because one
// line in Program.cs sets JsonNamingPolicy.SnakeCaseLower for the whole application.
// That is the same trick the Java implementation uses — and the same trap: a naming
// policy configured in one place and relied on in another is invisible at the point of
// use. When a field arrives as its default value instead of its real one, this is the
// first place to look.
//
// They live in one file because they are data, not behaviour, and reading them together
// is how you see the contract.

/// <summary>
/// One line of an incoming checkout request. Both properties nullable, because this is
/// untrusted input and a missing <c>qty</c> must be distinguishable from a zero one.
/// </summary>
public record OrderItem(string? Sku, long? Qty);

public record CreateOrderRequest(List<OrderItem>? Items);

/// <summary>
/// What catalog told us, at the moment we asked.
///
/// <para>Deliberately narrower than catalog's own product: orders has no business
/// carrying a stock level around, because nothing here acts on it. Take from a
/// dependency only what you use — every extra field is a thing that can change under
/// you and a coupling you did not need.</para>
/// </summary>
public record ProductSnapshot(string Sku, string Name, long PriceCents);

/// <summary>
/// <c>Name</c> and <c>UnitCents</c> are copied from catalog at purchase time.
///
/// <para>Not caching, and not denormalisation for speed — correctness. An order records
/// what was sold, and catalog is free to re-price tomorrow. It also happens to be what
/// lets <c>GET /v1/orders/{id}</c> answer without calling anybody: a dependency you do
/// not have cannot be down.</para>
/// </summary>
public record OrderLine(string Sku, string Name, long UnitCents, long Qty);

public record Payment(string Status, string? AuthCode);

public record Order(string Id, string Status, long TotalCents, string CreatedAt,
                    List<OrderLine> Lines, Payment? Payment);
