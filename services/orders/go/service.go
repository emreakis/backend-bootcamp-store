package main

import (
	"context"
	"log"
	"time"

	"github.com/google/uuid"
)

// service is one user action, three services, two protocols.
//
// Open monolith/go/internal/orders/orders.go next to this file. The steps are the same
// three: price the lines, charge the card, write the order. Almost every line of
// difference is a consequence of those steps now crossing a network.
type service struct {
	repo     *repository
	catalog  *catalogClient
	payments *paymentsClient
}

// checkout — NOTE WHAT IS MISSING FROM THIS METHOD: a transaction around the whole
// thing.
//
// That is deliberate, and it is the single most important structural decision in this
// service.
//
// The obvious move is to Begin() at the top and Commit() at the bottom, the way the
// monolith does. Do that and you hold a database connection open across two network
// calls. A slow payments service then does not merely make checkout slow — it pins one
// connection per in-flight order until the pool is empty, at which point every other
// endpoint in this service stops working too, including the ones that never touch
// payments. You would have converted a payments outage into a total outage, via your
// connection pool.
//
// So: talk to the network first, hold no locks while doing it, and open a short local
// transaction only once you have everything you need to write.
//
// The cost is that steps 1-2 and step 3 are no longer atomic together. If this process
// dies between the charge and the insert, the customer is charged for an order that
// does not exist. That is a real hole, and the honest answers to it — an outbox, a
// reconciliation job, a saga — are the module after this bootcamp. The monolith closed
// it with one keyword. Nothing here closes it for free.
func (s *service) checkout(ctx context.Context, items []orderItem, idempotencyKey string) (*order, error) {
	if err := validate(items); err != nil {
		return nil, err
	}

	// Did we already do exactly this? A dropped response is indistinguishable from a
	// failed request, so a good client retries — and this is what makes that retry
	// safe rather than expensive.
	if idempotencyKey != "" {
		if seen, ok := s.repo.findOrderIDByIdempotencyKey(ctx, idempotencyKey); ok {
			log.Printf("idempotency_key=%s REPLAYED -> order=%s", idempotencyKey, seen)
			return s.getOrder(ctx, seen)
		}
	}

	orderID := uuid.NewString()
	createdAt := time.Now().UTC().Truncate(time.Second)

	// 1. Price every line against catalog, over REST. A 404 here becomes a designed
	//    order rejection; an unreachable catalog becomes a 503.
	lines := make([]orderLine, 0, len(items))
	var totalCents int64
	for _, item := range items {
		product, err := s.catalog.fetch(item.Sku)
		if err != nil {
			return nil, err
		}
		lines = append(lines, orderLine{
			Sku: product.Sku, Name: product.Name,
			UnitCents: product.PriceCents, Qty: *item.Qty,
		})
		totalCents += product.PriceCents * *item.Qty
	}

	// 2. Charge, over gRPC.
	//
	//    The idempotency key handed downstream is the ORDER ID when the client did not
	//    supply one — stable across this service's own internal retries, which is what
	//    exercise 3.2 depends on. It is deliberately NOT stable across two separate
	//    client calls with no Idempotency-Key: that is the client choosing to have no
	//    protection, and the contract says so out loud.
	downstreamKey := idempotencyKey
	if downstreamKey == "" {
		downstreamKey = orderID
	}
	pay, err := s.payments.charge(orderID, totalCents, downstreamKey)
	if err != nil {
		return nil, err
	}

	// 3. Now, and only now, a short local transaction.
	if err := s.repo.persist(ctx, orderID, createdAt, totalCents, lines, pay, idempotencyKey); err != nil {
		return nil, err
	}

	log.Printf("order=%s CONFIRMED total=%d lines=%d", orderID, totalCents, len(lines))
	return &order{
		ID:         orderID,
		Status:     "CONFIRMED",
		TotalCents: totalCents,
		CreatedAt:  createdAt.Format(time.RFC3339),
		Lines:      lines,
		Payment:    pay,
	}, nil
}

func (s *service) getOrder(ctx context.Context, id string) (*order, error) {
	found, ok := s.repo.findOrder(ctx, id)
	if !ok {
		return nil, orderNotFound(id)
	}
	return found, nil
}

// cancel an order.
//
// Shorter than the monolith's version, because there is no stock to put back — this
// system never took any.
//
// What it also does not do is refund the card, and that omission is worth naming
// rather than hiding. A refund is a second call to a service that can be down, and
// doing it inline would make cancellation fail whenever payments is unwell. It belongs
// on a queue, retried until it succeeds. That is the same "after the charge, not in
// front of the customer" pattern as confirmation emails and inventory — the module
// after this bootcamp.
func (s *service) cancel(ctx context.Context, id string) (*order, error) {
	found, err := s.getOrder(ctx, id)
	if err != nil {
		return nil, err
	}
	if found.Status != "CONFIRMED" {
		return nil, orderNotCancellable(id, found.Status)
	}
	if err := s.repo.markCancelled(ctx, id); err != nil {
		return nil, err
	}
	log.Printf("order=%s CANCELLED", id)
	found.Status = "CANCELLED"
	return found, nil
}

func validate(items []orderItem) error {
	if len(items) == 0 {
		return validationFailed("An order needs at least one item.")
	}
	for _, item := range items {
		if item.Sku == "" {
			return validationFailed("Every item needs a sku.")
		}
		if item.Qty == nil || *item.Qty < 1 {
			return validationFailed("Every item needs a qty of at least 1.")
		}
	}
	return nil
}
