package io.backendguru.store.orders;

/** One line of an incoming checkout request. Boxed so a missing qty is null, not 0. */
public record OrderItem(String sku, Long qty) {
}
