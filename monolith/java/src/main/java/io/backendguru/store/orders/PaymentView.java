package io.backendguru.store.orders;

/**
 * What the order API shows of a payment. Deliberately narrower than the payments
 * module's own record: the internal payment id and amount are not the order's to
 * publish. Deciding what a module exposes is the same decision Session 2 makes about
 * what goes in a contract.
 */
public record PaymentView(String status, String authCode) {
}
