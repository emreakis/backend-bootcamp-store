package io.backendguru.store.orders;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

/**
 * Everything this service knows how to persist — and it is only ever its own tables.
 *
 * <p>There is no {@code products} table here to join to. Catalog's data lives in a
 * different database, in a different container, behind a different set of
 * credentials, and no query in this file could reach it if it wanted to.
 */
@Repository
public class OrdersRepository {

    private final JdbcTemplate jdbc;

    OrdersRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<OrderLine> LINE_MAPPER = (rs, i) -> new OrderLine(
            rs.getString("sku"), rs.getString("name"),
            rs.getLong("unit_cents"), rs.getLong("qty"));

    public Optional<String> findOrderIdByIdempotencyKey(String key) {
        return jdbc.query("SELECT order_id FROM idempotency_keys WHERE key = ?",
                        (rs, i) -> rs.getString("order_id"), key)
                .stream().findFirst();
    }

    /**
     * The whole write, in one short local transaction.
     *
     * <p>This is what is left of the monolith's checkout transaction. It still spans
     * the order, its lines and the payment outcome, because those all live here — but
     * it no longer spans catalog's stock, because catalog's stock is in another
     * database and no transaction manager on earth will help you.
     *
     * <p>Note how little time it is open for. Both network calls already happened,
     * outside. See the comment in {@link OrdersService#checkout}.
     */
    @Transactional
    public void persist(String id, Instant createdAt, long totalCents, List<OrderLine> lines,
                        ChargeOutcome payment, String idempotencyKey) {

        jdbc.update("INSERT INTO orders (id, status, total_cents, created_at, payment_status,"
                        + " payment_auth_code) VALUES (?, ?, ?, ?, ?, ?)",
                UUID.fromString(id), "CONFIRMED", totalCents, Timestamp.from(createdAt),
                payment.status(), payment.authCode());

        for (OrderLine line : lines) {
            jdbc.update("INSERT INTO order_lines (order_id, sku, name, unit_cents, qty)"
                            + " VALUES (?, ?, ?, ?, ?)",
                    UUID.fromString(id), line.sku(), line.name(), line.unitCents(), line.qty());
        }

        // Written in the SAME transaction as the order. If it were a second, separate
        // write, a crash between the two would leave an order whose idempotency key
        // was never recorded — and the client's retry would cheerfully create a
        // duplicate. Atomicity is still available here; it is only cross-service
        // atomicity that is gone.
        if (idempotencyKey != null && !idempotencyKey.isBlank()) {
            jdbc.update("INSERT INTO idempotency_keys (key, order_id, created_at) VALUES (?, ?, ?)",
                    idempotencyKey, UUID.fromString(id), Timestamp.from(createdAt));
        }
    }

    public Optional<Order> findOrder(String id) {
        UUID uuid;
        try {
            uuid = UUID.fromString(id);
        } catch (IllegalArgumentException notAUuid) {
            return Optional.empty();
        }

        List<Order> found = jdbc.query(
                "SELECT id, status, total_cents, created_at, payment_status, payment_auth_code"
                        + " FROM orders WHERE id = ?",
                (rs, i) -> new Order(
                        rs.getString("id"),
                        rs.getString("status"),
                        rs.getLong("total_cents"),
                        rs.getTimestamp("created_at").toInstant().toString().replace(".000Z", "Z"),
                        List.of(),
                        rs.getString("payment_status") == null ? null
                                : new PaymentView(rs.getString("payment_status"),
                                        rs.getString("payment_auth_code"))),
                uuid);

        if (found.isEmpty()) {
            return Optional.empty();
        }

        Order header = found.get(0);
        List<OrderLine> lines = jdbc.query(
                "SELECT sku, name, unit_cents, qty FROM order_lines WHERE order_id = ? ORDER BY sku",
                LINE_MAPPER, uuid);

        return Optional.of(new Order(header.id(), header.status(), header.totalCents(),
                header.createdAt(), lines, header.payment()));
    }

    @Transactional
    public void markCancelled(String id) {
        jdbc.update("UPDATE orders SET status = ? WHERE id = ?", "CANCELLED", UUID.fromString(id));
    }
}
