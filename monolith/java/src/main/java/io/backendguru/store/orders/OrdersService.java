package io.backendguru.store.orders;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import io.backendguru.store.DomainException;
import io.backendguru.store.catalog.CatalogService;
import io.backendguru.store.catalog.Product;
import io.backendguru.store.payments.Payment;
import io.backendguru.store.payments.PaymentsService;

/**
 * MODULE: orders — owns {@code orders} and {@code order_lines}.
 *
 * <p>Public API: {@code checkout}, {@code getOrder}, {@code cancel}.
 *
 * <p>The orchestrator, and the only module that depends on the other two. Trace the
 * call chain in {@code checkout} — it is the same chain Session 3 draws across three
 * services, except that here every arrow is a method call that cannot fail on its own.
 */
@Service
public class OrdersService {

    private final JdbcTemplate jdbc;
    // Injected because these are the other modules' public APIs. This constructor is
    // the dependency arrow on the Session 1 architecture diagram.
    private final CatalogService catalog;
    private final PaymentsService payments;

    OrdersService(JdbcTemplate jdbc, CatalogService catalog, PaymentsService payments) {
        this.jdbc = jdbc;
        this.catalog = catalog;
        this.payments = payments;
    }

    private static final RowMapper<OrderLine> LINE_MAPPER = (rs, rowNum) -> new OrderLine(
            rs.getString("sku"), rs.getString("name"),
            rs.getLong("unit_cents"), rs.getLong("qty"));

    /**
     * One user action, three modules, one transaction.
     *
     * <p>{@code @Transactional} is the whole lesson in one annotation. It opens a
     * transaction, binds its connection to this thread, and every statement any module
     * runs from here joins it. If anything throws, all of it disappears.
     *
     * <p>Read this next to the Session 3 diagram of the same flow. The steps are
     * identical. The difference is that every step here either happens or does not
     * happen, together, and there is no state in between for anyone to observe.
     *
     * <p>In Session 3 these three modules become three services with three databases
     * and this annotation becomes a lie you cannot tell. Everything you will learn
     * about sagas, idempotency and retries exists to buy back a fraction of what this
     * one line does for free.
     */
    @Transactional
    public Order checkout(List<OrderItem> items) {
        if (items == null || items.isEmpty()) {
            throw DomainException.validationFailed("An order needs at least one item.");
        }
        for (OrderItem item : items) {
            if (item.sku() == null || item.sku().isBlank()) {
                throw DomainException.validationFailed("Every item needs a sku.");
            }
            if (item.qty() == null || item.qty() < 1) {
                throw DomainException.validationFailed("Every item needs a qty of at least 1.");
            }
        }

        String id = UUID.randomUUID().toString();
        String createdAt = Instant.now().truncatedTo(ChronoUnit.SECONDS).toString();

        // 1. Reserve stock and capture the price AS IT IS NOW. Calling into catalog,
        //    never touching its table.
        List<OrderLine> lines = new ArrayList<>();
        long totalCents = 0;
        for (OrderItem item : items) {
            Product product = catalog.reserve(item.sku(), item.qty());
            lines.add(new OrderLine(product.sku(), product.name(), product.priceCents(), item.qty()));
            totalCents += product.priceCents() * item.qty();
        }

        // 2. Write the order. The line rows copy name and unit_cents on purpose: an
        //    order records what was sold, not what the catalog says next week.
        jdbc.update("INSERT INTO orders (id, status, total_cents, created_at) VALUES (?, ?, ?, ?)",
                id, "CONFIRMED", totalCents, createdAt);
        for (OrderLine line : lines) {
            jdbc.update("INSERT INTO order_lines (order_id, sku, name, unit_cents, qty)"
                    + " VALUES (?, ?, ?, ?, ?)",
                    id, line.sku(), line.name(), line.unitCents(), line.qty());
        }

        // 3. Charge. A decline throws, the transaction rolls back, and the stock
        //    reserved in step 1 is back on the shelf without anyone writing code to put
        //    it there. That last clause is what Session 3 costs you.
        Payment payment = payments.charge(id, totalCents);

        return new Order(id, "CONFIRMED", totalCents, createdAt, lines,
                new PaymentView(payment.status(), payment.authCode()));
    }

    public Order getOrder(String id) {
        List<Order> found = jdbc.query(
                "SELECT id, status, total_cents, created_at FROM orders WHERE id = ?",
                (rs, rowNum) -> new Order(rs.getString("id"), rs.getString("status"),
                        rs.getLong("total_cents"), rs.getString("created_at"), null, null),
                id);
        if (found.isEmpty()) {
            throw DomainException.orderNotFound(id);
        }
        Order order = found.get(0);

        List<OrderLine> lines = jdbc.query(
                "SELECT sku, name, unit_cents, qty FROM order_lines WHERE order_id = ? ORDER BY sku",
                LINE_MAPPER, id);

        // Again: through the module's API, not its table.
        Payment payment = payments.findForOrder(id);

        return new Order(order.id(), order.status(), order.totalCents(), order.createdAt(),
                lines, payment == null ? null : new PaymentView(payment.status(), payment.authCode()));
    }

    /**
     * Cancels an order and puts its stock back.
     *
     * <p>Cancelling an already-cancelled order is a 409, not a 400 and not a 500. The
     * request was well formed and the server is healthy; the resource is simply not in
     * a state where this makes sense.
     */
    @Transactional
    public Order cancel(String id) {
        Order order = getOrder(id);
        if (!"CONFIRMED".equals(order.status())) {
            throw DomainException.orderNotCancellable(id, order.status());
        }

        for (OrderLine line : order.lines()) {
            catalog.release(line.sku(), line.qty());
        }
        jdbc.update("UPDATE orders SET status = ? WHERE id = ?", "CANCELLED", id);

        return new Order(order.id(), "CANCELLED", order.totalCents(), order.createdAt(),
                order.lines(), order.payment());
    }
}
