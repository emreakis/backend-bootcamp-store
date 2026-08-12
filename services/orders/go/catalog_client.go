package main

import (
	"encoding/json"
	"fmt"
	"log"
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
	// TODO (exercise 3.4) — GIVE THIS CLIENT A TIMEOUT.
	//
	// http.Client's zero value has no timeout. None. Its patience is unbounded, and
	// cfg.catalogTimeout above is read from the environment and then quietly ignored.
	//
	// Go makes this one a single field, which is either a gift or a trap depending on
	// whether you remember it exists:
	//
	//     &http.Client{Timeout: cfg.catalogTimeout}
	//
	// That covers connect, redirects, reading the body — the whole round trip. For
	// finer control (a short connect deadline, a longer read) you build a
	// *http.Transport instead, and in a real service you probably should: the two
	// failures are different, and a slow body is not the same problem as an
	// unreachable host.
	//
	// Payments gets all the attention because it is the dramatic failure, but catalog
	// sits on the same checkout path: a slow catalog blocks exactly the same
	// goroutines, and does it one step earlier.
	//
	// Then prove it: `docker compose pause catalog` and post an order. Before the fix
	// the request hangs; after it, you get a 503 in one second. `pause` rather than
	// `stop`, because a stopped container refuses connections instantly and a paused
	// one leaves you hanging — which is the whole point.
	// ====================================================================
	client := &http.Client{}

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
