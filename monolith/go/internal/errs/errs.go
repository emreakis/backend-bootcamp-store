// Package errs holds domain outcomes, not accidents.
//
// Every constructor below names a thing the business decided can happen. They are
// returned deep inside a module and translated to HTTP exactly once, at the edge,
// in main.go.
//
// That translation is the whole discipline: a missing product must leave this
// process as a designed 404, never as a stack trace. An API that only documents its
// successes is half designed.
package errs

import "fmt"

// Error carries everything the HTTP edge needs to render an RFC 9457 problem
// document, and nothing about HTTP itself beyond the status code.
type Error struct {
	Kind   string // becomes the `type` suffix
	Title  string
	Status int
	Detail string
}

func (e *Error) Error() string { return e.Detail }

func ValidationFailed(detail string) *Error {
	return &Error{"validation-failed", "Validation failed", 400, detail}
}

func ProductNotFound(sku string) *Error {
	return &Error{"product-not-found", "Product not found", 404,
		fmt.Sprintf("No product with sku '%s'.", sku)}
}

func InsufficientStock(sku string, requested, available int64) *Error {
	return &Error{"insufficient-stock", "Insufficient stock", 409,
		fmt.Sprintf("Product '%s' has %d in stock, %d requested.", sku, available, requested)}
}

func OrderNotFound(id string) *Error {
	return &Error{"order-not-found", "Order not found", 404,
		fmt.Sprintf("No order with id '%s'.", id)}
}

// OrderNotCancellable is a state conflict — not a bad request, and not a server
// bug. This is what 409 is for, and it is the status code most APIs forget to use.
func OrderNotCancellable(id, status string) *Error {
	return &Error{"order-not-cancellable", "Order not cancellable", 409,
		fmt.Sprintf("Order '%s' is %s and cannot be cancelled.", id, status)}
}

func PaymentDeclined(detail string) *Error {
	return &Error{"payment-declined", "Payment declined", 402, detail}
}
