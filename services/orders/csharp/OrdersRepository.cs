using Npgsql;

namespace Orders;

/// <summary>
/// Everything this service knows how to persist — and it is only ever its own tables.
///
/// <para>There is no <c>products</c> table here to join to. Catalog's data lives in a
/// different database, in a different container, behind a different set of credentials,
/// and no query in this file could reach it if it wanted to.</para>
/// </summary>
public class OrdersRepository : IAsyncDisposable
{
    private readonly NpgsqlDataSource _db;

    public OrdersRepository() => _db = NpgsqlDataSource.Create(Config.ConnectionString());

    /// <summary>
    /// Wait for the database rather than crashing if it is a second behind. compose
    /// already gates startup on a healthcheck; this is the belt to that braces, because
    /// in a real platform nothing promises your dependencies start first.
    /// </summary>
    public async Task WaitForDatabaseAsync(ILogger log)
    {
        var deadline = DateTime.UtcNow.AddSeconds(30);
        while (true)
        {
            try
            {
                await using var command = _db.CreateCommand("SELECT 1");
                await command.ExecuteScalarAsync();
                return;
            }
            catch (NpgsqlException) when (DateTime.UtcNow < deadline)
            {
                log.LogWarning("waiting for the database");
                await Task.Delay(500);
            }
        }
    }

    public async Task<string?> FindOrderIdByIdempotencyKeyAsync(string key)
    {
        await using var command = _db.CreateCommand(
            "SELECT order_id FROM idempotency_keys WHERE key = $1");
        command.Parameters.AddWithValue(key);
        var found = await command.ExecuteScalarAsync();
        return found is Guid id ? id.ToString() : null;
    }

    /// <summary>
    /// The whole write, in one short local transaction.
    ///
    /// <para>This is what is left of the monolith's checkout transaction. It still spans
    /// the order, its lines and the payment outcome, because those all live here — but
    /// it no longer spans catalog's stock, because catalog's stock is in another
    /// database and no transaction manager on earth will help you.</para>
    ///
    /// <para>Note how little time it is open for. Both network calls already happened,
    /// outside. See the comment on <see cref="OrdersService.CheckoutAsync"/>.</para>
    /// </summary>
    public async Task PersistAsync(string id, DateTime createdAt, long totalCents,
                                   List<OrderLine> lines, Payment payment, string? idempotencyKey)
    {
        var orderId = Guid.Parse(id);

        await using var connection = await _db.OpenConnectionAsync();
        await using var transaction = await connection.BeginTransactionAsync();

        await using (var command = new NpgsqlCommand(
            """
            INSERT INTO orders (id, status, total_cents, created_at, payment_status,
                                payment_auth_code) VALUES ($1, $2, $3, $4, $5, $6)
            """, connection, transaction))
        {
            command.Parameters.AddWithValue(orderId);
            command.Parameters.AddWithValue("CONFIRMED");
            command.Parameters.AddWithValue(totalCents);
            command.Parameters.AddWithValue(createdAt);
            command.Parameters.AddWithValue(payment.Status);
            command.Parameters.AddWithValue((object?)payment.AuthCode ?? DBNull.Value);
            await command.ExecuteNonQueryAsync();
        }

        foreach (var line in lines)
        {
            await using var command = new NpgsqlCommand(
                """
                INSERT INTO order_lines (order_id, sku, name, unit_cents, qty)
                VALUES ($1, $2, $3, $4, $5)
                """, connection, transaction);
            command.Parameters.AddWithValue(orderId);
            command.Parameters.AddWithValue(line.Sku);
            command.Parameters.AddWithValue(line.Name);
            command.Parameters.AddWithValue(line.UnitCents);
            command.Parameters.AddWithValue(line.Qty);
            await command.ExecuteNonQueryAsync();
        }

        // Written in the SAME transaction as the order. If it were a second, separate
        // write, a crash between the two would leave an order whose idempotency key was
        // never recorded — and the client's retry would cheerfully create a duplicate.
        // Atomicity is still available here; it is only cross-service atomicity that is
        // gone.
        if (!string.IsNullOrWhiteSpace(idempotencyKey))
        {
            await using var command = new NpgsqlCommand(
                "INSERT INTO idempotency_keys (key, order_id, created_at) VALUES ($1, $2, $3)",
                connection, transaction);
            command.Parameters.AddWithValue(idempotencyKey);
            command.Parameters.AddWithValue(orderId);
            command.Parameters.AddWithValue(createdAt);
            await command.ExecuteNonQueryAsync();
        }

        await transaction.CommitAsync();
    }

    public async Task<Order?> FindOrderAsync(string id)
    {
        // Not a uuid at all, so it cannot name an order. A 404 rather than a 500 or a
        // Postgres `invalid input syntax for type uuid` leaking out through the driver.
        if (!Guid.TryParse(id, out var orderId)) return null;

        Order? header = null;
        await using (var command = _db.CreateCommand(
            """
            SELECT id, status, total_cents, created_at, payment_status, payment_auth_code
            FROM orders WHERE id = $1
            """))
        {
            command.Parameters.AddWithValue(orderId);
            await using var reader = await command.ExecuteReaderAsync();
            if (!await reader.ReadAsync()) return null;

            header = new Order(
                reader.GetGuid(0).ToString(),
                reader.GetString(1),
                reader.GetInt64(2),
                Iso(reader.GetDateTime(3)),
                [],
                reader.IsDBNull(4) ? null
                    : new Payment(reader.GetString(4), reader.IsDBNull(5) ? null : reader.GetString(5)));
        }

        var lines = new List<OrderLine>();
        await using (var command = _db.CreateCommand(
            "SELECT sku, name, unit_cents, qty FROM order_lines WHERE order_id = $1 ORDER BY sku"))
        {
            command.Parameters.AddWithValue(orderId);
            await using var reader = await command.ExecuteReaderAsync();
            while (await reader.ReadAsync())
            {
                lines.Add(new OrderLine(reader.GetString(0), reader.GetString(1),
                    reader.GetInt64(2), reader.GetInt64(3)));
            }
        }

        return header with { Lines = lines };
    }

    public async Task MarkCancelledAsync(string id)
    {
        await using var command = _db.CreateCommand("UPDATE orders SET status = $1 WHERE id = $2");
        command.Parameters.AddWithValue("CANCELLED");
        command.Parameters.AddWithValue(Guid.Parse(id));
        await command.ExecuteNonQueryAsync();
    }

    /// <summary>RFC 3339, UTC, seconds precision — what the contract says.</summary>
    public static string Iso(DateTime moment) =>
        moment.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ");

    public async ValueTask DisposeAsync() => await _db.DisposeAsync();
}
