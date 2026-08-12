package io.backendguru.store.payments;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Service;

import io.backendguru.store.DomainException;

/**
 * MODULE: payments — owns {@code payments}.
 *
 * <p>Public API: {@code charge}, {@code findForOrder}.
 *
 * <p>Stands in for a real card provider. In Session 3 this module becomes a gRPC
 * service and {@code charge} becomes a network call with a deadline, a retry policy
 * and a circuit breaker in front of it. Today it is a method call: it cannot time
 * out, it cannot be down, and it cannot answer twice.
 */
@Service
public class PaymentsService {

    private final JdbcTemplate jdbc;
    private final long declineOverCents;
    private final boolean alwaysDecline;

    PaymentsService(JdbcTemplate jdbc,
                    @Value("${store.payment.decline-over-cents}") long declineOverCents,
                    @Value("${store.payment.always-decline}") boolean alwaysDecline) {
        this.jdbc = jdbc;
        this.declineOverCents = declineOverCents;
        this.alwaysDecline = alwaysDecline;
    }

    private static final RowMapper<Payment> ROW_MAPPER = (rs, rowNum) -> new Payment(
            rs.getString("id"), rs.getString("order_id"), rs.getLong("amount_cents"),
            rs.getString("status"), rs.getString("auth_code"));

    /**
     * The payment recorded against an order, if there is one.
     *
     * <p>{@code orders} needs this to render an order, and {@code orders} may not read
     * the {@code payments} table — so the need becomes a method on this module's
     * public API. That is the rule doing its job: every cross-module need surfaces as
     * a call, and every call is a candidate to become a network hop on Saturday.
     */
    public Payment findForOrder(String orderId) {
        List<Payment> found = jdbc.query(
                "SELECT id, order_id, amount_cents, status, auth_code FROM payments"
                        + " WHERE order_id = ? ORDER BY created_at DESC LIMIT 1",
                ROW_MAPPER, orderId);
        return found.isEmpty() ? null : found.get(0);
    }

    /**
     * Charges the card, records the attempt and returns the authorisation.
     *
     * <p>Declines are recorded too. An audit trail with only the successes in it is
     * not an audit trail — and when this becomes a remote service, "did the charge
     * happen?" is a question you will need the database to answer.
     */
    public Payment charge(String orderId, long amountCents) {
        boolean declined = alwaysDecline || amountCents > declineOverCents;

        Payment payment = new Payment(
                UUID.randomUUID().toString(), orderId, amountCents,
                declined ? "DECLINED" : "APPROVED",
                declined ? null : "AUTH-" + UUID.randomUUID().toString()
                        .replace("-", "").substring(0, 8).toUpperCase());

        jdbc.update("INSERT INTO payments (id, order_id, amount_cents, status, auth_code,"
                        + " created_at) VALUES (?, ?, ?, ?, ?, ?)",
                payment.id(), payment.orderId(), payment.amountCents(), payment.status(),
                payment.authCode(), Instant.now().truncatedTo(ChronoUnit.SECONDS).toString());

        if (declined) {
            // Throwing here rolls back the caller's transaction — including this
            // INSERT. That is the honest trade: we lose the record of the decline, but
            // we cannot possibly leave a confirmed order behind an unpaid card.
            // Session 3 has to choose between those two outcomes explicitly, because
            // it can no longer have both.
            throw DomainException.paymentDeclined(
                    "Card declined for %d cents (limit %d).".formatted(amountCents, declineOverCents));
        }
        return payment;
    }
}
