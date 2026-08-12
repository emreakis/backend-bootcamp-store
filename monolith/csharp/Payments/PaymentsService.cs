namespace Store.Payments;

public sealed record Payment(string Id, string OrderId, long AmountCents, string Status,
    string? AuthCode);

/// <summary>
/// MODULE: payments — owns <c>payments</c>.
///
/// Public API: Charge, FindForOrder.
///
/// Stands in for a real card provider. In Session 3 this module becomes a gRPC service
/// and <c>Charge</c> becomes a network call with a deadline, a retry policy and a
/// circuit breaker in front of it. Today it is a method call: it cannot time out, it
/// cannot be down, and it cannot answer twice.
/// </summary>
public sealed class PaymentsService(Db db)
{
    /// <summary>
    /// The payment recorded against an order, if there is one.
    ///
    /// <c>orders</c> needs this to render an order, and <c>orders</c> may not read the
    /// <c>payments</c> table — so the need becomes a method on this module's public
    /// API. That is the rule doing its job: every cross-module need surfaces as a call,
    /// and every call is a candidate to become a network hop on Saturday.
    /// </summary>
    public Payment? FindForOrder(string orderId) =>
        db.QueryOne("SELECT id, order_id, amount_cents, status, auth_code FROM payments" +
            " WHERE order_id = ? ORDER BY created_at DESC LIMIT 1", MapPayment, orderId);

    /// <summary>
    /// Charges the card, records the attempt and returns the authorisation.
    ///
    /// Declines are recorded too. An audit trail with only the successes in it is not
    /// an audit trail — and when this becomes a remote service, "did the charge
    /// happen?" is a question you will need the database to answer.
    /// </summary>
    public Payment Charge(string orderId, long amountCents)
    {
        var declined = Config.PaymentAlwaysDecline || amountCents > Config.PaymentDeclineOverCents;

        var payment = new Payment(
            Guid.NewGuid().ToString(), orderId, amountCents,
            declined ? "DECLINED" : "APPROVED",
            declined ? null : $"AUTH-{Guid.NewGuid().ToString("N")[..8].ToUpperInvariant()}");

        db.Execute("INSERT INTO payments (id, order_id, amount_cents, status, auth_code," +
            " created_at) VALUES (?, ?, ?, ?, ?, ?)",
            payment.Id, payment.OrderId, payment.AmountCents, payment.Status, payment.AuthCode,
            DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"));

        if (declined)
        {
            // Throwing here rolls back the caller's transaction — including this INSERT.
            // That is the honest trade: we lose the record of the decline, but we cannot
            // possibly leave a confirmed order behind an unpaid card. Session 3 has to
            // choose between those two outcomes explicitly, because it can no longer
            // have both.
            throw DomainException.PaymentDeclined(
                $"Card declined for {amountCents} cents (limit {Config.PaymentDeclineOverCents}).");
        }
        return payment;
    }

    private static Payment MapPayment(Microsoft.Data.Sqlite.SqliteDataReader reader) =>
        new(reader.GetString(0), reader.GetString(1), reader.GetInt64(2), reader.GetString(3),
            reader.IsDBNull(4) ? null : reader.GetString(4));
}
