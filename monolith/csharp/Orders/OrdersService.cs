using Store.Catalog;
using Store.Payments;

namespace Store.Orders;

/// <summary>One line of an incoming checkout request. Nullable qty so a missing one is null, not 0.</summary>
public sealed record OrderItem(string? Sku, long? Qty);

public sealed record CreateOrderRequest(List<OrderItem>? Items);

/// <summary>
/// <c>Name</c> and <c>UnitCents</c> are copied from the product at purchase time, on
/// purpose. An order records what was sold, not what the catalog says next week — and
/// that copy is the part of this design that survives Session 3.
/// </summary>
public sealed record OrderLine(string Sku, string Name, long UnitCents, long Qty);

/// <summary>
/// What the order API shows of a payment. Deliberately narrower than the payments
/// module's own record: the internal payment id and amount are not the order's to
/// publish. Deciding what a module exposes is the same decision Session 2 makes about
/// what goes in a contract.
/// </summary>
public sealed record PaymentView(string Status, string? AuthCode);

public sealed record Order(string Id, string Status, long TotalCents, string CreatedAt,
    IReadOnlyList<OrderLine> Lines, PaymentView? Payment);

/// <summary>
/// MODULE: orders — owns <c>orders</c> and <c>order_lines</c>.
///
/// Public API: Checkout, GetOrder, Cancel.
///
/// The orchestrator, and the only module that depends on the other two. Trace the call
/// chain in <c>Checkout</c> — it is the same chain Session 3 draws across three
/// services, except that here every arrow is a method call that cannot fail on its own.
/// </summary>
public sealed class OrdersService(Db db, CatalogService catalog, PaymentsService payments)
{
    /// <summary>
    /// One user action, three modules, one transaction.
    ///
    /// Read this next to the Session 3 diagram of the same flow. The steps are
    /// identical. The difference is that every step here either happens or does not
    /// happen, together, and there is no state in between for anyone to observe.
    /// </summary>
    public Order Checkout(List<OrderItem>? items)
    {
        if (items is null || items.Count == 0)
        {
            throw DomainException.ValidationFailed("An order needs at least one item.");
        }
        foreach (var item in items)
        {
            if (string.IsNullOrEmpty(item.Sku))
            {
                throw DomainException.ValidationFailed("Every item needs a sku.");
            }
            if (item.Qty is null or < 1)
            {
                throw DomainException.ValidationFailed("Every item needs a qty of at least 1.");
            }
        }

        var id = Guid.NewGuid().ToString();
        var createdAt = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ");

        return db.Transaction(() =>
        {
            // 1. Reserve stock and capture the price AS IT IS NOW. Calling into catalog,
            //    never touching its table.
            var lines = new List<OrderLine>();
            long totalCents = 0;
            foreach (var item in items)
            {
                var product = catalog.Reserve(item.Sku!, item.Qty!.Value);
                lines.Add(new OrderLine(product.Sku, product.Name, product.PriceCents, item.Qty.Value));
                totalCents += product.PriceCents * item.Qty.Value;
            }

            // 2. Write the order. The line rows copy name and unit_cents on purpose: an
            //    order records what was sold, not what the catalog says next week.
            db.Execute("INSERT INTO orders (id, status, total_cents, created_at) VALUES (?, ?, ?, ?)",
                id, "CONFIRMED", totalCents, createdAt);
            foreach (var line in lines)
            {
                db.Execute("INSERT INTO order_lines (order_id, sku, name, unit_cents, qty)" +
                    " VALUES (?, ?, ?, ?, ?)", id, line.Sku, line.Name, line.UnitCents, line.Qty);
            }

            // 3. Charge. A decline throws, the transaction rolls back, and the stock
            //    reserved in step 1 is back on the shelf without anyone writing code to
            //    put it there. That last clause is what Session 3 costs you.
            var payment = payments.Charge(id, totalCents);

            return new Order(id, "CONFIRMED", totalCents, createdAt, lines,
                new PaymentView(payment.Status, payment.AuthCode));
        });
    }

    public Order GetOrder(string id)
    {
        var header = db.QueryOne(
            "SELECT id, status, total_cents, created_at FROM orders WHERE id = ?",
            reader => new Order(reader.GetString(0), reader.GetString(1),
                reader.GetInt64(2), reader.GetString(3), [], null),
            id) ?? throw DomainException.OrderNotFound(id);

        var lines = db.Query(
            "SELECT sku, name, unit_cents, qty FROM order_lines WHERE order_id = ? ORDER BY sku",
            reader => new OrderLine(reader.GetString(0), reader.GetString(1),
                reader.GetInt64(2), reader.GetInt64(3)),
            id);

        // Again: through the module's API, not its table.
        var payment = payments.FindForOrder(id);

        return header with
        {
            Lines = lines,
            Payment = payment is null ? null : new PaymentView(payment.Status, payment.AuthCode),
        };
    }

    /// <summary>
    /// Cancels an order and puts its stock back.
    ///
    /// Cancelling an already-cancelled order is a 409, not a 400 and not a 500. The
    /// request was well formed and the server is healthy; the resource is simply not in
    /// a state where this makes sense.
    /// </summary>
    public Order Cancel(string id)
    {
        var order = GetOrder(id);
        if (order.Status != "CONFIRMED")
        {
            throw DomainException.OrderNotCancellable(id, order.Status);
        }

        return db.Transaction(() =>
        {
            foreach (var line in order.Lines)
            {
                catalog.Release(line.Sku, line.Qty);
            }
            db.Execute("UPDATE orders SET status = ? WHERE id = ?", "CANCELLED", id);
            return order with { Status = "CANCELLED" };
        });
    }
}
