package io.backendguru.store.orders;

import java.util.List;

/**
 * The shapes this service reads and writes. Jackson renders every {@code camelCase}
 * component as {@code snake_case} because of the one naming-strategy line in
 * application.properties, so none of these needs an annotation.
 *
 * <p>They live in one file because they are data, not behaviour, and reading them
 * together is how you see the contract.
 */
final class Model {
    private Model() {
    }
}

/** One line of an incoming checkout request. Boxed qty so a missing one is null, not 0. */
record OrderItem(String sku, Long qty) {
}

record CreateOrderRequest(List<OrderItem> items) {
}

/**
 * What catalog told us, at the moment we asked.
 *
 * <p>Deliberately narrower than catalog's own product: orders has no business
 * carrying a stock level around, because nothing here acts on it. Take from a
 * dependency only what you use — every extra field is a thing that can change under
 * you and a coupling you did not need.
 */
record ProductSnapshot(String sku, String name, long priceCents) {
}

/** What catalog's JSON actually looks like on the wire. */
record CatalogProduct(String sku, String name, long priceCents, long stock) {
}

/**
 * {@code name} and {@code unitCents} are copied from catalog at purchase time.
 *
 * <p>Not caching, and not denormalisation for speed — correctness. An order records
 * what was sold, and catalog is free to re-price tomorrow. It also happens to be what
 * lets {@code GET /v1/orders/{id}} answer without calling anybody: a dependency you do
 * not have cannot be down.
 */
record OrderLine(String sku, String name, long unitCents, long qty) {
}

record PaymentView(String status, String authCode) {
}

record Order(String id, String status, long totalCents, String createdAt,
             List<OrderLine> lines, PaymentView payment) {
}

/** What the payments gRPC call gives back once a decline has been turned into a 402. */
record ChargeOutcome(String status, String authCode) {
}
