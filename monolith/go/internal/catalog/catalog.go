// Package catalog is a MODULE. It owns the `products` table.
//
// Public API: ListProducts, GetProduct, Reserve, Release.
//
// No other module may touch `products`. If orders wants a price it calls
// GetProduct; if it wants stock it calls Reserve. Go enforces the half of this that
// a compiler can: everything unexported here is unreachable from another package,
// so the module's public API is the only surface anyone can call. The other half —
// that the string "products" appears in no other package — is discipline, and it is
// what makes the Session 3 split a mechanical exercise rather than a rewrite.
package catalog

import (
	"database/sql"
	"errors"

	"github.com/backendguru/store/internal/errs"
	"github.com/backendguru/store/internal/storedb"
)

type Product struct {
	SKU        string `json:"sku"`
	Name       string `json:"name"`
	PriceCents int64  `json:"price_cents"`
	Stock      int64  `json:"stock"`
}

// ListProducts returns one page plus the cursor for the next.
//
// Keyset pagination, not OFFSET. An offset drifts: insert a product while a client
// is on page 2 and it either sees a row twice or misses one entirely. A cursor is a
// position in the data, not a count of rows someone else can change.
//
// We ask for limit+1 rows: if the extra one comes back, there is another page.
func ListProducts(q storedb.Querier, limit int, cursor string) ([]Product, *string, error) {
	var rows *sql.Rows
	var err error
	if cursor != "" {
		rows, err = q.Query("SELECT sku, name, price_cents, stock FROM products WHERE sku > ? ORDER BY sku LIMIT ?", cursor, limit+1)
	} else {
		rows, err = q.Query("SELECT sku, name, price_cents, stock FROM products ORDER BY sku LIMIT ?", limit+1)
	}
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()

	products := []Product{}
	for rows.Next() {
		var p Product
		if err := rows.Scan(&p.SKU, &p.Name, &p.PriceCents, &p.Stock); err != nil {
			return nil, nil, err
		}
		products = append(products, p)
	}
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}

	hasMore := len(products) > limit
	if hasMore {
		products = products[:limit]
	}
	var next *string
	if hasMore && len(products) > 0 {
		last := products[len(products)-1].SKU
		next = &last
	}
	return products, next, nil
}

func GetProduct(q storedb.Querier, sku string) (Product, error) {
	var p Product
	err := q.QueryRow("SELECT sku, name, price_cents, stock FROM products WHERE sku = ?", sku).
		Scan(&p.SKU, &p.Name, &p.PriceCents, &p.Stock)
	if errors.Is(err, sql.ErrNoRows) {
		return p, errs.ProductNotFound(sku)
	}
	return p, err
}

// Reserve takes qty units off the shelf and returns the product as it was priced.
//
// Note the shape of this call: the caller passes in its own Querier, so this runs
// inside the caller's transaction. Reserving stock and writing the order are one
// atomic act, and neither module had to know that.
//
// Once catalog is a separate service this parameter is the first thing to go — and
// with it, atomicity. What replaces it is a saga, and a compensating "un-reserve"
// that has to survive the process crashing between the two calls.
func Reserve(q storedb.Querier, sku string, qty int64) (Product, error) {
	product, err := GetProduct(q, sku)
	if err != nil {
		return product, err
	}
	if product.Stock < qty {
		return product, errs.InsufficientStock(sku, qty, product.Stock)
	}
	_, err = q.Exec("UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?", qty, sku, qty)
	return product, err
}

// Release puts stock back — used when an order is cancelled.
func Release(q storedb.Querier, sku string, qty int64) error {
	_, err := q.Exec("UPDATE products SET stock = stock + ? WHERE sku = ?", qty, sku)
	return err
}
