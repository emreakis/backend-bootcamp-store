package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
)

// catalogClient is the REST half of this service's dependencies.
//
// In the monolith this was catalog.GetProduct(db, sku) — a function call that could
// not fail on its own. It is now an HTTP request over a network, and every one of the
// eight fallacies applies to it.
type catalogClient struct {
	baseURL string
	http    *http.Client
}

func newCatalogClient(cfg config) *catalogClient {
	// ====================================================================
	// EXERCISE 3.4 — the timeout.
	//
	// http.Client.Timeout covers the whole round trip: connect, redirects, and reading
	// the body. One field, which is either a gift or a trap depending on whether you
	// remember it exists — its zero value means forever.
	//
	// The Transport underneath splits it further, and the split is the useful part:
	// DialContext's timeout is "I cannot reach this host", ResponseHeaderTimeout is
	// "this host accepted my connection and then went quiet". Different failures with
	// different causes, and only the second is what `docker compose pause catalog`
	// produces. Both are set from the same environment variable here because one number
	// is enough for a teaching system; in a real service the connect budget is usually
	// much tighter than the read budget.
	//
	// Prove it: `docker compose pause catalog` and post an order. Before this change
	// the request hung; now it is a 503 in one second.
	// ====================================================================
	client := &http.Client{
		Timeout: cfg.catalogTimeout,
		Transport: &http.Transport{
			DialContext:           (&net.Dialer{Timeout: cfg.catalogTimeout}).DialContext,
			ResponseHeaderTimeout: cfg.catalogTimeout,
		},
	}

	log.Printf("catalog client -> %s (timeout %s)", cfg.catalogURL, cfg.catalogTimeout)
	return &catalogClient{baseURL: cfg.catalogURL, http: client}
}

// fetch prices one sku.
//
// Three outcomes, and all three are designed:
//
//   - the product exists — we take its name and price and stop caring about it;
//   - catalog says 404 — a *designed order rejection*, not a 500. Passing a
//     dependency's status straight through would be lazy; letting it become a stack
//     trace would be worse;
//   - catalog cannot be reached — 503, because the customer did nothing wrong.
func (c *catalogClient) fetch(sku string) (productSnapshot, error) {
	response, err := c.http.Get(fmt.Sprintf("%s/v1/products/%s", c.baseURL, sku))
	if err != nil {
		// Connection refused, DNS failure, or a round trip that ran out of patience —
		// the last of which is only reachable once exercise 3.4 is done.
		log.Printf("catalog unreachable for sku=%s: %v", sku, err)
		return productSnapshot{}, catalogUnavailable(
			"The catalog service could not be reached. No order was placed.")
	}
	defer response.Body.Close()

	if response.StatusCode == http.StatusNotFound {
		return productSnapshot{}, productNotFound(sku)
	}
	if response.StatusCode != http.StatusOK {
		log.Printf("catalog answered %d for sku=%s", response.StatusCode, sku)
		return productSnapshot{}, catalogUnavailable(
			"The catalog service returned an unusable response. No order was placed.")
	}

	var product productSnapshot
	if err := json.NewDecoder(response.Body).Decode(&product); err != nil {
		return productSnapshot{}, catalogUnavailable(
			"The catalog service returned an unreadable response. No order was placed.")
	}
	return product, nil
}
