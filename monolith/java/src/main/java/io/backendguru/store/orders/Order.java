package io.backendguru.store.orders;

import java.util.List;

/** The order as the API renders it. */
public record Order(String id, String status, long totalCents, String createdAt,
                    List<OrderLine> lines, PaymentView payment) {
}
