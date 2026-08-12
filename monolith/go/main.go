// The HTTP layer. The only place in the process that knows what a status code is.
//
// Everything under internal/ is domain logic that would be identical in a desktop
// app. That separation is not decoration: in Session 3, catalog and payments grow
// their own HTTP and gRPC edges, and the module code underneath them barely changes.
package main

import (
	"database/sql"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strconv"

	"github.com/backendguru/store/internal/catalog"
	"github.com/backendguru/store/internal/config"
	"github.com/backendguru/store/internal/errs"
	"github.com/backendguru/store/internal/orders"
	"github.com/backendguru/store/internal/storedb"
)

const problemBase = "https://bootcamp.backendguru.io/problems/"

var db *sql.DB

func main() {
	var err error
	if db, err = storedb.Open(); err != nil {
		log.Fatalf("opening database: %v", err)
	}
	defer db.Close()
	if err := storedb.Bootstrap(db); err != nil {
		log.Fatalf("bootstrapping database: %v", err)
	}

	// Go 1.22+ patterns: the method is part of the route, and {sku} is a real path
	// variable. No router dependency needed for an API this size.
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", handle(health))
	mux.HandleFunc("GET /v1/products", handle(listProducts))
	mux.HandleFunc("GET /v1/products/{sku}", handle(getProduct))
	mux.HandleFunc("POST /v1/orders", handle(createOrder))
	mux.HandleFunc("GET /v1/orders/{id}", handle(getOrder))
	mux.HandleFunc("POST /v1/orders/{id}/cancel", handle(cancelOrder))

	log.Printf("store (%s) listening on :%s", config.Implementation, config.Port)
	if err := http.ListenAndServe(":"+config.Port, mux); err != nil {
		log.Fatal(err)
	}
}

// --- endpoints ---------------------------------------------------------------

// health is liveness only — it deliberately checks nothing downstream.
//
// Session 3 revisits this. A health check that calls its dependencies turns one
// service's outage into everyone's outage, because the platform starts killing
// healthy pods for being downstream of a sick one.
func health(w http.ResponseWriter, _ *http.Request) error {
	return writeJSON(w, 200, map[string]string{
		"status": "ok", "implementation": config.Implementation,
	})
}

func listProducts(w http.ResponseWriter, r *http.Request) error {
	limit := 20
	if raw := r.URL.Query().Get("limit"); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil || parsed < 1 || parsed > 100 {
			return errs.ValidationFailed("limit must be an integer between 1 and 100.")
		}
		limit = parsed
	}

	items, next, err := catalog.ListProducts(db, limit, r.URL.Query().Get("cursor"))
	if err != nil {
		return err
	}
	return writeJSON(w, 200, map[string]any{"items": items, "next_cursor": next})
}

func getProduct(w http.ResponseWriter, r *http.Request) error {
	product, err := catalog.GetProduct(db, r.PathValue("sku"))
	if err != nil {
		return err
	}
	return writeJSON(w, 200, product)
}

func createOrder(w http.ResponseWriter, r *http.Request) error {
	var body struct {
		Items []orders.Item `json:"items"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		return errs.ValidationFailed("Body must be a JSON object with an `items` array.")
	}

	order, err := orders.Checkout(db, body.Items)
	if err != nil {
		return err
	}
	w.Header().Set("Location", "/v1/orders/"+order.ID)
	return writeJSON(w, 201, order)
}

func getOrder(w http.ResponseWriter, r *http.Request) error {
	order, err := orders.GetOrder(db, r.PathValue("id"))
	if err != nil {
		return err
	}
	return writeJSON(w, 200, order)
}

func cancelOrder(w http.ResponseWriter, r *http.Request) error {
	order, err := orders.Cancel(db, r.PathValue("id"))
	if err != nil {
		return err
	}
	return writeJSON(w, 200, order)
}

// --- plumbing ----------------------------------------------------------------

type handlerFunc func(http.ResponseWriter, *http.Request) error

// handle translates a domain outcome into HTTP exactly once, for every route.
func handle(fn handlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if err := fn(w, r); err != nil {
			writeProblem(w, r, err)
		}
	}
}

func writeJSON(w http.ResponseWriter, status int, body any) error {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	return json.NewEncoder(w).Encode(body)
}

// writeProblem emits one error envelope, everywhere. RFC 9457 Problem Details.
//
// A client that learns this shape once handles every failure this API can produce.
// Bespoke error bodies per endpoint are how you make consumers write a parser per
// endpoint.
func writeProblem(w http.ResponseWriter, r *http.Request, err error) {
	var domain *errs.Error
	if !errors.As(err, &domain) {
		// Anything we did not name is a bug, and the caller must not be told to
		// change its request. 500, and the detail stays in our logs.
		log.Printf("unhandled error on %s: %v", r.URL.Path, err)
		domain = &errs.Error{Kind: "internal-error", Title: "Internal server error",
			Status: 500, Detail: "The request could not be completed."}
	}

	w.Header().Set("Content-Type", "application/problem+json")
	w.WriteHeader(domain.Status)
	json.NewEncoder(w).Encode(map[string]any{
		"type":     problemBase + domain.Kind,
		"title":    domain.Title,
		"status":   domain.Status,
		"detail":   domain.Detail,
		"instance": r.URL.Path,
	})
}
