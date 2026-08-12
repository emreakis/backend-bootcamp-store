// Package payments is a MODULE. It owns the `payments` table.
//
// Public API: Charge, FindForOrder.
//
// Stands in for a real card provider. In Session 3 this module becomes a gRPC
// service and Charge becomes a network call with a deadline, a retry policy and a
// circuit breaker in front of it. Today it is a function call: it cannot time out,
// it cannot be down, and it cannot answer twice.
package payments

import (
	"database/sql"
	"errors"
	"fmt"
	"time"

	"github.com/backendguru/store/internal/config"
	"github.com/backendguru/store/internal/errs"
	"github.com/backendguru/store/internal/id"
	"github.com/backendguru/store/internal/storedb"
)

type Payment struct {
	ID          string
	OrderID     string
	AmountCents int64
	Status      string
	AuthCode    *string
}

// FindForOrder returns the payment recorded against an order, if there is one.
//
// orders needs this to render an order, and orders may not read the `payments`
// table — so the need becomes a function on this module's public API. That is the
// rule doing its job: every cross-module need surfaces as a call, and every call is
// a candidate to become a network hop on Saturday.
func FindForOrder(q storedb.Querier, orderID string) (*Payment, error) {
	var p Payment
	var authCode sql.NullString
	err := q.QueryRow(
		"SELECT id, order_id, amount_cents, status, auth_code FROM payments WHERE order_id = ? ORDER BY created_at DESC LIMIT 1",
		orderID,
	).Scan(&p.ID, &p.OrderID, &p.AmountCents, &p.Status, &authCode)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if authCode.Valid {
		p.AuthCode = &authCode.String
	}
	return &p, nil
}

// Charge charges the card, records the attempt and returns the authorisation.
//
// Declines are recorded too. An audit trail with only the successes in it is not an
// audit trail — and when this becomes a remote service, "did the charge happen?" is
// a question you will need the database to answer.
func Charge(q storedb.Querier, orderID string, amountCents int64) (*Payment, error) {
	declined := config.PaymentAlwaysDecline || amountCents > config.PaymentDeclineOverCents

	payment := &Payment{
		ID:          id.New(),
		OrderID:     orderID,
		AmountCents: amountCents,
		Status:      "APPROVED",
	}
	if declined {
		payment.Status = "DECLINED"
	} else {
		code := "AUTH-" + id.Short()
		payment.AuthCode = &code
	}

	_, err := q.Exec(
		"INSERT INTO payments (id, order_id, amount_cents, status, auth_code, created_at) VALUES (?, ?, ?, ?, ?, ?)",
		payment.ID, payment.OrderID, payment.AmountCents, payment.Status, payment.AuthCode,
		time.Now().UTC().Format("2006-01-02T15:04:05Z"),
	)
	if err != nil {
		return nil, err
	}

	if declined {
		// Returning an error here rolls back the caller's transaction — including
		// this INSERT. That is the honest trade: we lose the record of the decline,
		// but we cannot possibly leave a confirmed order behind an unpaid card.
		// Session 3 has to choose between those two outcomes explicitly, because it
		// can no longer have both.
		return nil, errs.PaymentDeclined(fmt.Sprintf(
			"Card declined for %d cents (limit %d).", amountCents, config.PaymentDeclineOverCents))
	}
	return payment, nil
}
