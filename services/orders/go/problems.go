package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
)

// Domain outcomes, not accidents.
//
// Two of these did not exist in the monolith, and their arrival is the whole story of
// this session: catalogUnavailable and paymentsUnavailable. In one process, a module
// could not be down while its caller was up. Now it can, and the store owes its
// customers an honest answer when it happens.
//
// Note which failures are 4xx and which are 5xx, because the split is a blame
// assignment. A declined card is 402: the caller must change something (their card),
// and retrying identically will never help. A dependency being unreachable is 503: the
// caller did nothing wrong, should not change the request, and should come back later
// — which is what retryAfter tells them.
type domainError struct {
	kind       string
	title      string
	status     int
	detail     string
	retryAfter int // seconds; 0 means "do not send the header"
}

func (e *domainError) Error() string { return e.detail }

func validationFailed(detail string) *domainError {
	return &domainError{"validation-failed", "Validation failed", 400, detail, 0}
}

// productNotFound is catalog's 404, translated.
//
// Orders turns it into a designed order rejection rather than passing a dependency's
// status through blindly or letting it become a 500. Translating a dependency's
// vocabulary into your own is most of what an orchestrator is for.
func productNotFound(sku string) *domainError {
	return &domainError{"product-not-found", "Product not found", 404,
		fmt.Sprintf("No product with sku '%s'.", sku), 0}
}

func orderNotFound(id string) *domainError {
	return &domainError{"order-not-found", "Order not found", 404,
		fmt.Sprintf("No order with id '%s'.", id), 0}
}

// orderNotCancellable is a state conflict — well-formed request, healthy server,
// impossible transition.
func orderNotCancellable(id, status string) *domainError {
	return &domainError{"order-not-cancellable", "Order not cancellable", 409,
		fmt.Sprintf("Order '%s' is %s and cannot be cancelled.", id, status), 0}
}

func paymentDeclined(detail string) *domainError {
	return &domainError{"payment-declined", "Payment declined", 402, detail, 0}
}

func catalogUnavailable(detail string) *domainError {
	return &domainError{"catalog-unavailable", "Catalog unavailable", 503, detail, 5}
}

// paymentsUnavailable is the response the Session 3 exercise exists to produce.
//
// Getting a fast, honest 503 out of a payments outage is something you build. The
// default behaviour — no deadline, no breaker — is not this. It is every checkout
// goroutine blocking until the pool drains and the store goes down with its dependency.
func paymentsUnavailable(detail string) *domainError {
	return &domainError{"payments-unavailable", "Payments unavailable", 503, detail, 5}
}

const problemBase = "https://bootcamp.backendguru.io/problems/"

// writeProblem renders one error envelope, everywhere — RFC 9457, exactly as
// contracts/problem.yaml says.
func writeProblem(w http.ResponseWriter, r *http.Request, e *domainError) {
	w.Header().Set("Content-Type", "application/problem+json")
	if e.retryAfter > 0 {
		// Tells a well-behaved client when to come back, so it backs off instead of
		// joining the stampede that is currently keeping the dependency down.
		w.Header().Set("Retry-After", strconv.Itoa(e.retryAfter))
	}
	w.WriteHeader(e.status)
	_ = json.NewEncoder(w).Encode(map[string]any{
		"type":     problemBase + e.kind,
		"title":    e.title,
		"status":   e.status,
		"detail":   e.detail,
		"instance": r.URL.Path,
	})
}
