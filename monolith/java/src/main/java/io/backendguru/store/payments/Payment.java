package io.backendguru.store.payments;

public record Payment(String id, String orderId, long amountCents, String status,
                      String authCode) {
}
