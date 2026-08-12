package io.backendguru.store.catalog;

import java.util.List;

/** One page of products. {@code nextCursor} is null on the last page. */
public record ProductPage(List<Product> items, String nextCursor) {
}
