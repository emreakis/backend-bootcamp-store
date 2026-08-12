package io.backendguru.store.orders;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * One user action, three services, two protocols.
 *
 * <p>Open {@code monolith/java/.../orders/OrdersService.java} next to this file. The
 * steps are the same three: price the lines, charge the card, write the order. Almost
 * every line of difference is a consequence of those steps now crossing a network.
 */
@Service
public class OrdersService {

    private static final Logger log = LoggerFactory.getLogger(OrdersService.class);

    private final OrdersRepository repository;
    private final CatalogClient catalog;
    private final PaymentsClient payments;

    OrdersService(OrdersRepository repository, CatalogClient catalog, PaymentsClient payments) {
        this.repository = repository;
        this.catalog = catalog;
        this.payments = payments;
    }

    /**
     * NOTE WHAT IS MISSING FROM THIS METHOD: {@code @Transactional}.
     *
     * <p>That is deliberate, and it is the single most important structural decision
     * in this service.
     *
     * <p>The obvious move is to annotate the whole thing, the way the monolith does.
     * Do that and you hold a database connection open across two network calls. A slow
     * payments service then does not merely make checkout slow — it pins one
     * connection per in-flight order until the pool is empty, at which point every
     * other endpoint in this service stops working too, including the ones that never
     * touch payments. You would have converted a payments outage into a total outage,
     * via your connection pool.
     *
     * <p>So: talk to the network first, hold no locks while doing it, and open a short
     * local transaction only once you have everything you need to write.
     *
     * <p>The cost is that steps 1–2 and step 3 are no longer atomic together. If this
     * process dies between the charge and the insert, the customer is charged for an
     * order that does not exist. That is a real hole, and the honest answers to it —
     * an outbox, a reconciliation job, a saga — are the module after this bootcamp.
     * The monolith closed it with one keyword. Nothing here closes it for free.
     */
    public Order checkout(List<OrderItem> items, String idempotencyKey) {
        validate(items);

        // Did we already do exactly this? A dropped response is indistinguishable from
        // a failed request, so a good client retries — and this is what makes that
        // retry safe rather than expensive.
        if (idempotencyKey != null && !idempotencyKey.isBlank()) {
            var seen = repository.findOrderIdByIdempotencyKey(idempotencyKey);
            if (seen.isPresent()) {
                log.info("idempotency_key={} REPLAYED -> order={}", idempotencyKey, seen.get());
                return getOrder(seen.get());
            }
        }

        String orderId = UUID.randomUUID().toString();
        Instant createdAt = Instant.now().truncatedTo(ChronoUnit.SECONDS);

        // 1. Price every line against catalog, over REST. A 404 here becomes a
        //    designed order rejection; an unreachable catalog becomes a 503.
        List<OrderLine> lines = new ArrayList<>();
        long totalCents = 0;
        for (OrderItem item : items) {
            ProductSnapshot product = catalog.fetch(item.sku());
            lines.add(new OrderLine(product.sku(), product.name(), product.priceCents(), item.qty()));
            totalCents += product.priceCents() * item.qty();
        }

        // 2. Charge, over gRPC.
        //
        //    The idempotency key handed downstream is the ORDER ID when the client did
        //    not supply one — stable across this service's own internal retries, which
        //    is what exercise 3.2 depends on. It is deliberately NOT stable across two
        //    separate client calls with no Idempotency-Key: that is the client
        //    choosing to have no protection, and the contract says so out loud.
        String downstreamKey = (idempotencyKey == null || idempotencyKey.isBlank())
                ? orderId : idempotencyKey;
        ChargeOutcome payment = payments.charge(orderId, totalCents, downstreamKey);

        // 3. Now, and only now, a short local transaction.
        repository.persist(orderId, createdAt, totalCents, lines, payment, idempotencyKey);

        log.info("order={} CONFIRMED total={} lines={}", orderId, totalCents, lines.size());
        return new Order(orderId, "CONFIRMED", totalCents,
                createdAt.toString(), lines, new PaymentView(payment.status(), payment.authCode()));
    }

    public Order getOrder(String id) {
        return repository.findOrder(id).orElseThrow(() -> DomainException.orderNotFound(id));
    }

    /**
     * Cancel an order.
     *
     * <p>Shorter than the monolith's version, because there is no stock to put back —
     * this system never took any.
     *
     * <p>What it also does not do is refund the card, and that omission is worth
     * naming rather than hiding. A refund is a second call to a service that can be
     * down, and doing it inline would make cancellation fail whenever payments is
     * unwell. It belongs on a queue, retried until it succeeds. That is the same
     * "after the charge, not in front of the customer" pattern as confirmation emails
     * and inventory — the module after this bootcamp.
     */
    public Order cancel(String id) {
        Order order = getOrder(id);
        if (!"CONFIRMED".equals(order.status())) {
            throw DomainException.orderNotCancellable(id, order.status());
        }
        repository.markCancelled(id);
        log.info("order={} CANCELLED", id);
        return new Order(order.id(), "CANCELLED", order.totalCents(), order.createdAt(),
                order.lines(), order.payment());
    }

    private void validate(List<OrderItem> items) {
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
    }
}
