package io.backendguru.store.catalog;

/**
 * The catalog module's public data. Jackson renders {@code priceCents} as
 * {@code price_cents} because of the one naming-strategy line in
 * application.properties — no annotation needed on any component.
 */
public record Product(String sku, String name, long priceCents, long stock) {
}
