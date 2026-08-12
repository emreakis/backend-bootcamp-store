package io.backendguru.store.orders;

/**
 * {@code name} and {@code unitCents} are copied from the product at purchase time, on
 * purpose. An order records what was sold, not what the catalog says next week — and
 * that copy is the part of this design that survives Session 3.
 */
public record OrderLine(String sku, String name, long unitCents, long qty) {
}
