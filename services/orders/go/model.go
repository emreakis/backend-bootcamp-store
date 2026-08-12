package main

// The shapes this service reads and writes.
//
// The struct tags are the contract, and in Go they are the only thing standing between
// `TotalCents` and a JSON key called `TotalCents`. Every field on the wire is
// snake_case because contracts/orders.v1.yaml says so — not because a convention was
// felt to be nicer.
//
// They live in one file because they are data, not behaviour, and reading them
// together is how you see the contract.

// orderItem is one line of an incoming checkout request.
//
// Qty is a *int64 rather than an int64 on purpose. Go zeroes missing JSON fields, so
// an absent qty and an explicit `"qty": 0` are indistinguishable in a plain int — and
// one of those is a client bug we must reject while the other is a client bug we must
// reject with a different message. The pointer is how you get field presence back.
type orderItem struct {
	Sku string `json:"sku"`
	Qty *int64 `json:"qty"`
}

type createOrderRequest struct {
	Items []orderItem `json:"items"`
}

// productSnapshot is what catalog told us, at the moment we asked.
//
// Deliberately narrower than catalog's own product: orders has no business carrying a
// stock level around, because nothing here acts on it. Take from a dependency only
// what you use — every extra field is a thing that can change under you and a coupling
// you did not need.
type productSnapshot struct {
	Sku        string `json:"sku"`
	Name       string `json:"name"`
	PriceCents int64  `json:"price_cents"`
}

// orderLine's Name and UnitCents are copied from catalog at purchase time.
//
// Not caching, and not denormalisation for speed — correctness. An order records what
// was sold, and catalog is free to re-price tomorrow. It also happens to be what lets
// GET /v1/orders/{id} answer without calling anybody: a dependency you do not have
// cannot be down.
type orderLine struct {
	Sku       string `json:"sku"`
	Name      string `json:"name"`
	UnitCents int64  `json:"unit_cents"`
	Qty       int64  `json:"qty"`
}

type payment struct {
	Status   string `json:"status"`
	AuthCode string `json:"auth_code"`
}

type order struct {
	ID         string      `json:"id"`
	Status     string      `json:"status"`
	TotalCents int64       `json:"total_cents"`
	CreatedAt  string      `json:"created_at"`
	Lines      []orderLine `json:"lines"`
	Payment    *payment    `json:"payment"`
}
