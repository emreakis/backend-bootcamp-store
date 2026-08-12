// CATALOG — the read side of the store, and the simplest service in the system.
//
// Small enough to read in full, which is why it is the one to read first. Everything
// here satisfies contracts/catalog.v1.yaml; if this file and that file disagree, this
// file is wrong.
//
// Compare it with monolith/go/internal/catalog. The SQL is identical. What changed is
// everything around it: its own database, its own process, its own deployment, and a
// Reserve function that no longer exists because stock cannot be taken off a shelf in
// one database inside a transaction that lives in another.
//
// No web framework. net/http has had method-aware routing and path wildcards since Go
// 1.22, so `GET /v1/products/{sku}` below is the standard library and nothing else.
package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const implementation = "go"

const problemBase = "https://bootcamp.backendguru.io/problems/"

type product struct {
	Sku        string `json:"sku"`
	Name       string `json:"name"`
	PriceCents int64  `json:"price_cents"`
	Stock      int64  `json:"stock"`
}

type productPage struct {
	Items []product `json:"items"`
	// A pointer so that the last page serialises `"next_cursor": null` rather than
	// `""`. The contract says null, and an empty string is a different value that
	// happens to look falsy in most languages — which is exactly how a client ends up
	// paginating forever.
	NextCursor *string `json:"next_cursor"`
}

var pool *pgxpool.Pool

func main() {
	port := env("PORT", "8000")
	databaseURL := env("DATABASE_URL", "postgres://store:store@localhost:5433/catalog")

	ctx := context.Background()
	var err error
	if pool, err = pgxpool.New(ctx, databaseURL); err != nil {
		log.Fatalf("database: %v", err)
	}
	defer pool.Close()

	// Wait for the database rather than crashing if it is a second behind. compose
	// already gates startup on a healthcheck; this is the belt to that braces, because
	// in a real platform nothing promises your dependencies start first.
	deadline := time.Now().Add(30 * time.Second)
	for pool.Ping(ctx) != nil {
		if time.Now().After(deadline) {
			log.Fatal("the database never became reachable")
		}
		time.Sleep(500 * time.Millisecond)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", health)
	mux.HandleFunc("GET /v1/products", listProducts)
	mux.HandleFunc("GET /v1/products/{sku}", getProduct)
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		writeProblem(w, r, 404, "product-not-found", "Product not found",
			"No product with sku '"+r.URL.Path+"'.")
	})

	server := &http.Server{
		Addr:              ":" + port,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	log.Printf("catalog (%s) listening on :%s", implementation, port)
	log.Fatal(server.ListenAndServe())
}

// health is liveness only — it does not touch the database.
//
// Tempting to run `SELECT 1` here. Don't. If this endpoint failed whenever Postgres
// hiccupped, the platform would start killing catalog pods during a database blip,
// removing capacity exactly when the system is least able to spare it.
func health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK,
		map[string]string{"status": "ok", "implementation": implementation})
}

// listProducts paginates by keyset, not by offset.
//
// An offset drifts under concurrent inserts; a cursor is a position in the data rather
// than a count of rows someone else can change.
//
// Ask for limit + 1 rows: if the extra one comes back, there is another page.
func listProducts(w http.ResponseWriter, r *http.Request) {
	limit := int64(20)
	if raw := r.URL.Query().Get("limit"); raw != "" {
		parsed, err := strconv.ParseInt(raw, 10, 64)
		if err != nil || parsed < 1 || parsed > 100 {
			// The contract declares 1..100 and says an out-of-range value is a 400 in
			// the usual envelope. Nothing enforces that for you here — Go hands you a
			// string and an opinion is required. Which is honest: every framework in
			// this repo has a different default, and every one of them is wrong until
			// somebody checks it against the spec.
			writeProblem(w, r, 400, "validation-failed", "Validation failed",
				"limit must be an integer between 1 and 100.")
			return
		}
		limit = parsed
	}

	var (
		rows pgx.Rows
		err  error
	)

	if cursor := r.URL.Query().Get("cursor"); cursor != "" {
		rows, err = pool.Query(r.Context(),
			"SELECT sku, name, price_cents, stock FROM products"+
				" WHERE sku > $1 ORDER BY sku LIMIT $2", cursor, limit+1)
	} else {
		rows, err = pool.Query(r.Context(),
			"SELECT sku, name, price_cents, stock FROM products ORDER BY sku LIMIT $1",
			limit+1)
	}
	if err != nil {
		internalError(w, r, err)
		return
	}
	defer rows.Close()

	// An empty slice, never nil: json.Marshal writes a nil slice as `null`, and the
	// contract says `items` is an array.
	items := []product{}
	for rows.Next() {
		var found product
		if err := rows.Scan(&found.Sku, &found.Name, &found.PriceCents, &found.Stock); err != nil {
			internalError(w, r, err)
			return
		}
		items = append(items, found)
	}

	var nextCursor *string
	if int64(len(items)) > limit {
		items = items[:limit]
		nextCursor = &items[len(items)-1].Sku
	}
	writeJSON(w, http.StatusOK, productPage{Items: items, NextCursor: nextCursor})
}

// getProduct is the call `orders` makes during checkout.
//
// Its 404 is the most consequential response in this service. Orders has to turn it
// into a designed order rejection — so it must be unambiguous, carry the sku that was
// missing, and never arrive as a 500. A dependency that fails clearly is a dependency
// you can build on.
func getProduct(w http.ResponseWriter, r *http.Request) {
	sku := r.PathValue("sku")

	var found product
	err := pool.QueryRow(r.Context(),
		"SELECT sku, name, price_cents, stock FROM products WHERE sku = $1", sku).
		Scan(&found.Sku, &found.Name, &found.PriceCents, &found.Stock)
	if err != nil {
		writeProblem(w, r, 404, "product-not-found", "Product not found",
			"No product with sku '"+sku+"'.")
		return
	}
	writeJSON(w, http.StatusOK, found)
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

// writeProblem renders one error envelope, everywhere — RFC 9457, exactly as
// contracts/problem.yaml says.
func writeProblem(w http.ResponseWriter, r *http.Request, status int, kind, title, detail string) {
	w.Header().Set("Content-Type", "application/problem+json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{
		"type":     problemBase + kind,
		"title":    title,
		"status":   status,
		"detail":   detail,
		"instance": r.URL.Path,
	})
}

// internalError: anything unnamed is a bug. 500, and the detail stays in our logs —
// never in a response body, where it becomes a client's problem to parse and an
// attacker's to read.
func internalError(w http.ResponseWriter, r *http.Request, err error) {
	log.Printf("unhandled error on %s: %v", r.URL.Path, err)
	writeProblem(w, r, 500, "internal-error", "Internal server error",
		"The request could not be completed.")
}

func env(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
