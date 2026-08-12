namespace Orders;

/// <summary>
/// One user action, three services, two protocols.
///
/// <para>Open <c>monolith/csharp/Orders/OrdersService.cs</c> next to this file. The
/// steps are the same three: price the lines, charge the card, write the order. Almost
/// every line of difference is a consequence of those steps now crossing a
/// network.</para>
/// </summary>
public class OrdersService(
    OrdersRepository repository,
    CatalogClient catalog,
    PaymentsClient payments,
    ILogger<OrdersService> log)
{
    /// <summary>
    /// NOTE WHAT IS MISSING FROM THIS METHOD: a transaction around the whole thing.
    ///
    /// <para>That is deliberate, and it is the single most important structural
    /// decision in this service.</para>
    ///
    /// <para>The obvious move is to open a connection at the top and commit at the
    /// bottom, the way the monolith does. Do that and you hold a database connection
    /// open across two network calls. A slow payments service then does not merely make
    /// checkout slow — it pins one connection per in-flight order until the pool is
    /// empty (ten, here), at which point every other endpoint in this service stops
    /// working too, including the ones that never touch payments. You would have
    /// converted a payments outage into a total outage, via your connection pool.</para>
    ///
    /// <para>So: talk to the network first, hold no locks while doing it, and open a
    /// short local transaction only once you have everything you need to write.</para>
    ///
    /// <para>The cost is that steps 1-2 and step 3 are no longer atomic together. If
    /// this process dies between the charge and the insert, the customer is charged for
    /// an order that does not exist. That is a real hole, and the honest answers to it —
    /// an outbox, a reconciliation job, a saga — are the module after this bootcamp. The
    /// monolith closed it with one keyword. Nothing here closes it for free.</para>
    /// </summary>
    public async Task<Order> CheckoutAsync(List<OrderItem>? items, string? idempotencyKey)
    {
        Validate(items);

        // Did we already do exactly this? A dropped response is indistinguishable from a
        // failed request, so a good client retries — and this is what makes that retry
        // safe rather than expensive.
        if (!string.IsNullOrWhiteSpace(idempotencyKey))
        {
            var seen = await repository.FindOrderIdByIdempotencyKeyAsync(idempotencyKey);
            if (seen is not null)
            {
                log.LogInformation("idempotency_key={Key} REPLAYED -> order={Order}",
                    idempotencyKey, seen);
                return await GetOrderAsync(seen);
            }
        }

        var orderId = Guid.NewGuid().ToString();
        var createdAt = new DateTime(
            DateTime.UtcNow.Ticks / TimeSpan.TicksPerSecond * TimeSpan.TicksPerSecond,
            DateTimeKind.Utc);

        // 1. Price every line against catalog, over REST. A 404 here becomes a designed
        //    order rejection; an unreachable catalog becomes a 503.
        var lines = new List<OrderLine>();
        long totalCents = 0;
        foreach (var item in items!)
        {
            var product = await catalog.FetchAsync(item.Sku!);
            lines.Add(new OrderLine(product.Sku, product.Name, product.PriceCents, item.Qty!.Value));
            totalCents += product.PriceCents * item.Qty!.Value;
        }

        // 2. Charge, over gRPC.
        //
        //    The idempotency key handed downstream is the ORDER ID when the client did
        //    not supply one — stable across this service's own internal retries, which is
        //    what exercise 3.2 depends on. It is deliberately NOT stable across two
        //    separate client calls with no Idempotency-Key: that is the client choosing
        //    to have no protection, and the contract says so out loud.
        var downstreamKey = string.IsNullOrWhiteSpace(idempotencyKey) ? orderId : idempotencyKey;
        var payment = await payments.ChargeAsync(orderId, totalCents, downstreamKey);

        // 3. Now, and only now, a short local transaction.
        await repository.PersistAsync(orderId, createdAt, totalCents, lines, payment, idempotencyKey);

        log.LogInformation("order={Order} CONFIRMED total={Total} lines={Lines}",
            orderId, totalCents, lines.Count);
        return new Order(orderId, "CONFIRMED", totalCents,
            OrdersRepository.Iso(createdAt), lines, payment);
    }

    public async Task<Order> GetOrderAsync(string id) =>
        await repository.FindOrderAsync(id) ?? throw DomainException.OrderNotFound(id);

    /// <summary>
    /// Cancel an order.
    ///
    /// <para>Shorter than the monolith's version, because there is no stock to put back
    /// — this system never took any.</para>
    ///
    /// <para>What it also does not do is refund the card, and that omission is worth
    /// naming rather than hiding. A refund is a second call to a service that can be
    /// down, and doing it inline would make cancellation fail whenever payments is
    /// unwell. It belongs on a queue, retried until it succeeds. That is the same "after
    /// the charge, not in front of the customer" pattern as confirmation emails and
    /// inventory — the module after this bootcamp.</para>
    /// </summary>
    public async Task<Order> CancelAsync(string id)
    {
        var order = await GetOrderAsync(id);
        if (order.Status != "CONFIRMED")
        {
            throw DomainException.OrderNotCancellable(id, order.Status);
        }
        await repository.MarkCancelledAsync(id);
        log.LogInformation("order={Order} CANCELLED", id);
        return order with { Status = "CANCELLED" };
    }

    private static void Validate(List<OrderItem>? items)
    {
        if (items is null || items.Count == 0)
        {
            throw DomainException.ValidationFailed("An order needs at least one item.");
        }
        foreach (var item in items)
        {
            if (string.IsNullOrWhiteSpace(item.Sku))
            {
                throw DomainException.ValidationFailed("Every item needs a sku.");
            }
            if (item.Qty is null or < 1)
            {
                throw DomainException.ValidationFailed("Every item needs a qty of at least 1.");
            }
        }
    }
}
