// Package orders is a MODULE. It owns `orders` and `order_lines`.
//
// Public API: Checkout, GetOrder, Cancel.
//
// The orchestrator, and the only module that depends on the other two. Trace the
// call chain in Checkout — it is the same chain Session 3 draws across three
// services, except that here every arrow is a function call that cannot fail on its
// own.
package orders

import (
	"database/sql"
	"time"

	"github.com/backendguru/store/internal/catalog"
	"github.com/backendguru/store/internal/errs"
	"github.com/backendguru/store/internal/id"
	"github.com/backendguru/store/internal/payments"
	"github.com/backendguru/store/internal/storedb"
)

type Item struct {
	SKU string `json:"sku"`
	Qty int64  `json:"qty"`
}

type Line struct {
	SKU       string `json:"sku"`
	Name      string `json:"name"`
	UnitCents int64  `json:"unit_cents"`
	Qty       int64  `json:"qty"`
}

type PaymentView struct {
	Status   string  `json:"status"`
	AuthCode *string `json:"auth_code"`
}

type Order struct {
	ID         string       `json:"id"`
	Status     string       `json:"status"`
	TotalCents int64        `json:"total_cents"`
	CreatedAt  string       `json:"created_at"`
	Lines      []Line       `json:"lines"`
	Payment    *PaymentView `json:"payment"`
}

// Checkout is one user action, three modules, one transaction.
//
// Read this next to the Session 3 diagram of the same flow. The steps are
// identical. The difference is that every step here either happens or does not
// happen, together, and there is no state in between for anyone to observe.
func Checkout(db *sql.DB, items []Item) (*Order, error) {
	if len(items) == 0 {
		return nil, errs.ValidationFailed("An order needs at least one item.")
	}
	for _, item := range items {
		if item.SKU == "" {
			return nil, errs.ValidationFailed("Every item needs a sku.")
		}
		if item.Qty < 1 {
			return nil, errs.ValidationFailed("Every item needs a qty of at least 1.")
		}
	}

	orderID := id.New()
	createdAt := time.Now().UTC().Format("2006-01-02T15:04:05Z")
	var order *Order

	err := storedb.InTx(db, func(tx *sql.Tx) error {
		// 1. Reserve stock and capture the price AS IT IS NOW. Calling into
		//    catalog, never touching its table.
		lines := make([]Line, 0, len(items))
		var totalCents int64
		for _, item := range items {
			product, err := catalog.Reserve(tx, item.SKU, item.Qty)
			if err != nil {
				return err
			}
			lines = append(lines, Line{product.SKU, product.Name, product.PriceCents, item.Qty})
			totalCents += product.PriceCents * item.Qty
		}

		// 2. Write the order. The line rows copy name and unit_cents on purpose: an
		//    order records what was sold, not what the catalog says next week.
		if _, err := tx.Exec(
			"INSERT INTO orders (id, status, total_cents, created_at) VALUES (?, ?, ?, ?)",
			orderID, "CONFIRMED", totalCents, createdAt,
		); err != nil {
			return err
		}
		for _, line := range lines {
			if _, err := tx.Exec(
				"INSERT INTO order_lines (order_id, sku, name, unit_cents, qty) VALUES (?, ?, ?, ?, ?)",
				orderID, line.SKU, line.Name, line.UnitCents, line.Qty,
			); err != nil {
				return err
			}
		}

		// 3. Charge. A decline returns an error, the transaction rolls back, and the
		//    stock reserved in step 1 is back on the shelf without anyone writing
		//    code to put it there. That last clause is what Session 3 costs you.
		payment, err := payments.Charge(tx, orderID, totalCents)
		if err != nil {
			return err
		}

		order = &Order{
			ID: orderID, Status: "CONFIRMED", TotalCents: totalCents,
			CreatedAt: createdAt, Lines: lines,
			Payment: &PaymentView{payment.Status, payment.AuthCode},
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return order, nil
}

func GetOrder(q storedb.Querier, orderID string) (*Order, error) {
	order := &Order{ID: orderID, Lines: []Line{}}
	err := q.QueryRow("SELECT status, total_cents, created_at FROM orders WHERE id = ?", orderID).
		Scan(&order.Status, &order.TotalCents, &order.CreatedAt)
	if err == sql.ErrNoRows {
		return nil, errs.OrderNotFound(orderID)
	}
	if err != nil {
		return nil, err
	}

	rows, err := q.Query(
		"SELECT sku, name, unit_cents, qty FROM order_lines WHERE order_id = ? ORDER BY sku", orderID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var line Line
		if err := rows.Scan(&line.SKU, &line.Name, &line.UnitCents, &line.Qty); err != nil {
			return nil, err
		}
		order.Lines = append(order.Lines, line)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	// Again: through the module's API, not its table.
	payment, err := payments.FindForOrder(q, orderID)
	if err != nil {
		return nil, err
	}
	if payment != nil {
		order.Payment = &PaymentView{payment.Status, payment.AuthCode}
	}
	return order, nil
}

// Cancel cancels an order and puts its stock back.
//
// Cancelling an already-cancelled order is a 409, not a 400 and not a 500. The
// request was well formed and the server is healthy; the resource is simply not in
// a state where this makes sense.
func Cancel(db *sql.DB, orderID string) (*Order, error) {
	order, err := GetOrder(db, orderID)
	if err != nil {
		return nil, err
	}
	if order.Status != "CONFIRMED" {
		return nil, errs.OrderNotCancellable(orderID, order.Status)
	}

	err = storedb.InTx(db, func(tx *sql.Tx) error {
		for _, line := range order.Lines {
			if err := catalog.Release(tx, line.SKU, line.Qty); err != nil {
				return err
			}
		}
		_, err := tx.Exec("UPDATE orders SET status = ? WHERE id = ?", "CANCELLED", orderID)
		return err
	})
	if err != nil {
		return nil, err
	}

	order.Status = "CANCELLED"
	return order, nil
}
