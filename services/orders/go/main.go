// ORDERS — the orchestrator.
//
// REST at the edge, gRPC inside, two databases it cannot join across, and the only
// service in this system that can be woken up by somebody else's outage.
//
// Everything here satisfies contracts/orders.v1.yaml; if this file and that file
// disagree, this file is wrong.
//
// No web framework. Go's net/http has had method-aware routing and path wildcards
// since 1.22, so `POST /v1/orders` and `r.PathValue("id")` below are the standard
// library and nothing else. Fewer dependencies is not a virtue in itself; being able
// to read the whole request path without learning a framework first is.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"time"
)

func main() {
	cfg := load()
	ctx := context.Background()

	repo, err := newRepository(ctx, cfg.databaseURL)
	if err != nil {
		log.Fatalf("database: %v", err)
	}
	defer repo.close()

	payments, err := newPaymentsClient(cfg)
	if err != nil {
		log.Fatalf("payments client: %v", err)
	}
	defer payments.close()

	svc := &service{repo: repo, catalog: newCatalogClient(cfg), payments: payments}
	mux := http.NewServeMux()

	// Liveness only, and here that matters more than anywhere else in the system.
	//
	// Orders has dependencies, so the temptation to check them is real. Give in to it
	// and a payments outage makes orders report unhealthy, and the platform starts
	// restarting orders pods — removing capacity from a service that was working,
	// during an incident, because we told it to.
	//
	// Orders is not sick when payments is down. It is degraded. That distinction
	// belongs in metrics and alerts, not in the endpoint an orchestrator uses to
	// decide whether to kill you.
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK,
			map[string]string{"status": "ok", "implementation": implementation})
	})

	mux.HandleFunc("POST /v1/orders", func(w http.ResponseWriter, r *http.Request) {
		var body createOrderRequest
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			writeProblem(w, r, validationFailed("Body must be a JSON object with an `items` array."))
			return
		}

		placed, err := svc.checkout(r.Context(), body.Items, r.Header.Get("Idempotency-Key"))
		if err != nil {
			fail(w, r, err)
			return
		}
		w.Header().Set("Location", "/v1/orders/"+placed.ID)
		writeJSON(w, http.StatusCreated, placed)
	})

	mux.HandleFunc("GET /v1/orders/{id}", func(w http.ResponseWriter, r *http.Request) {
		found, err := svc.getOrder(r.Context(), r.PathValue("id"))
		if err != nil {
			fail(w, r, err)
			return
		}
		writeJSON(w, http.StatusOK, found)
	})

	mux.HandleFunc("POST /v1/orders/{id}/cancel", func(w http.ResponseWriter, r *http.Request) {
		cancelled, err := svc.cancel(r.Context(), r.PathValue("id"))
		if err != nil {
			fail(w, r, err)
			return
		}
		writeJSON(w, http.StatusOK, cancelled)
	})

	// A path that matches no route. Go's default is `404 page not found` as plain
	// text, which is a fine answer for a browser and a useless one for a client that
	// parses every other error out of this service as a problem document. One
	// envelope, everywhere, including the boring cases.
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		writeProblem(w, r, orderNotFound(r.URL.Path))
	})

	server := &http.Server{
		Addr:              ":" + cfg.port,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	log.Printf("orders (%s) listening on :%s", implementation, cfg.port)
	log.Fatal(server.ListenAndServe())
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

// fail turns an error into a response.
//
// A *domainError is something this service decided; anything else is a bug, gets a
// 500, and keeps its detail in our logs — never in a response body, where it becomes a
// client's problem to parse and an attacker's to read.
func fail(w http.ResponseWriter, r *http.Request, err error) {
	var designed *domainError
	if errors.As(err, &designed) {
		writeProblem(w, r, designed)
		return
	}
	log.Printf("unhandled error on %s: %v", r.URL.Path, err)
	writeProblem(w, r, &domainError{
		kind:   "internal-error",
		title:  "Internal server error",
		status: http.StatusInternalServerError,
		detail: "The request could not be completed.",
	})
}
