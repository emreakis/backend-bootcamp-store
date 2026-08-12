package main

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

// repository is everything this service knows how to persist — and it is only ever its
// own tables.
//
// There is no products table here to join to. Catalog's data lives in a different
// database, in a different container, behind a different set of credentials, and no
// query in this file could reach it if it wanted to.
type repository struct {
	pool *pgxpool.Pool
}

func newRepository(ctx context.Context, databaseURL string) (*repository, error) {
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		return nil, err
	}

	// Wait for the database rather than crashing if it is a second behind. compose
	// already gates startup on a healthcheck; this is the belt to that braces, because
	// in a real platform nothing promises your dependencies start first.
	deadline := time.Now().Add(30 * time.Second)
	for {
		if err = pool.Ping(ctx); err == nil {
			break
		}
		if time.Now().After(deadline) {
			return nil, err
		}
		time.Sleep(500 * time.Millisecond)
	}
	return &repository{pool: pool}, nil
}

func (r *repository) close() { r.pool.Close() }

func (r *repository) findOrderIDByIdempotencyKey(ctx context.Context, key string) (string, bool) {
	var id uuid.UUID
	err := r.pool.QueryRow(ctx,
		"SELECT order_id FROM idempotency_keys WHERE key = $1", key).Scan(&id)
	if err != nil {
		return "", false
	}
	return id.String(), true
}

// persist is the whole write, in one short local transaction.
//
// This is what is left of the monolith's checkout transaction. It still spans the
// order, its lines and the payment outcome, because those all live here — but it no
// longer spans catalog's stock, because catalog's stock is in another database and no
// transaction manager on earth will help you.
//
// Note how little time it is open for. Both network calls already happened, outside.
// See the comment on service.checkout.
func (r *repository) persist(ctx context.Context, id string, createdAt time.Time,
	totalCents int64, lines []orderLine, pay *payment, idempotencyKey string) error {

	orderUUID, err := uuid.Parse(id)
	if err != nil {
		return err
	}

	tx, err := r.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx) //nolint:errcheck // no-op once Commit has succeeded

	if _, err = tx.Exec(ctx,
		`INSERT INTO orders (id, status, total_cents, created_at, payment_status,
		                     payment_auth_code) VALUES ($1, $2, $3, $4, $5, $6)`,
		orderUUID, "CONFIRMED", totalCents, createdAt, pay.Status, pay.AuthCode); err != nil {
		return err
	}

	for _, line := range lines {
		if _, err = tx.Exec(ctx,
			`INSERT INTO order_lines (order_id, sku, name, unit_cents, qty)
			 VALUES ($1, $2, $3, $4, $5)`,
			orderUUID, line.Sku, line.Name, line.UnitCents, line.Qty); err != nil {
			return err
		}
	}

	// Written in the SAME transaction as the order. If it were a second, separate
	// write, a crash between the two would leave an order whose idempotency key was
	// never recorded — and the client's retry would cheerfully create a duplicate.
	// Atomicity is still available here; it is only cross-service atomicity that is
	// gone.
	if idempotencyKey != "" {
		if _, err = tx.Exec(ctx,
			"INSERT INTO idempotency_keys (key, order_id, created_at) VALUES ($1, $2, $3)",
			idempotencyKey, orderUUID, createdAt); err != nil {
			return err
		}
	}

	return tx.Commit(ctx)
}

func (r *repository) findOrder(ctx context.Context, id string) (*order, bool) {
	orderUUID, err := uuid.Parse(id)
	if err != nil {
		// Not a uuid at all, so it cannot name an order. A 404 rather than a 500 or a
		// database error leaking out through the driver.
		return nil, false
	}

	var (
		found       order
		createdAt   time.Time
		payStatus   *string
		payAuthCode *string
	)
	err = r.pool.QueryRow(ctx,
		`SELECT id, status, total_cents, created_at, payment_status, payment_auth_code
		 FROM orders WHERE id = $1`, orderUUID).
		Scan(&found.ID, &found.Status, &found.TotalCents, &createdAt, &payStatus, &payAuthCode)
	if err != nil {
		return nil, false
	}
	found.CreatedAt = createdAt.UTC().Format(time.RFC3339)

	rows, err := r.pool.Query(ctx,
		"SELECT sku, name, unit_cents, qty FROM order_lines WHERE order_id = $1 ORDER BY sku",
		orderUUID)
	if err != nil {
		return nil, false
	}
	defer rows.Close()

	// An empty slice, never nil: `json.Marshal(nil slice)` writes `null`, and the
	// contract says `lines` is an array. Six languages, six different ways to get this
	// subtly wrong.
	found.Lines = []orderLine{}
	for rows.Next() {
		var line orderLine
		if err := rows.Scan(&line.Sku, &line.Name, &line.UnitCents, &line.Qty); err != nil {
			return nil, false
		}
		found.Lines = append(found.Lines, line)
	}

	if payStatus != nil {
		auth := ""
		if payAuthCode != nil {
			auth = *payAuthCode
		}
		found.Payment = &payment{Status: *payStatus, AuthCode: auth}
	}
	return &found, true
}

func (r *repository) markCancelled(ctx context.Context, id string) error {
	orderUUID, err := uuid.Parse(id)
	if err != nil {
		return err
	}
	_, err = r.pool.Exec(ctx, "UPDATE orders SET status = $1 WHERE id = $2",
		"CANCELLED", orderUUID)
	return err
}
