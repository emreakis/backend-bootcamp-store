# The contract all six implementations satisfy

This is the specification. Every implementation in `monolith/` matches it exactly —
same paths, same status codes, same JSON field names, same error bodies. If two
implementations disagree, one of them has a bug; `tools/smoke.sh` is the arbiter.

In Session 2 this informal document becomes a real OpenAPI 3.1 contract under
`contracts/`. Keep it around and compare — the gap between "we wrote down what it
does" and "we published a contract others can generate code from" is most of the
lesson.

**Base URL:** `http://localhost:8080` **Content type:** `application/json`

---

## Errors — RFC 9457 Problem Details

Every non-2xx response, in every implementation, in every language, has this shape
and the content type `application/problem+json`:

```json
{
  "type":     "https://bootcamp.backendguru.io/problems/product-not-found",
  "title":    "Product not found",
  "status":   404,
  "detail":   "No product with sku 'ZZZ-999'.",
  "instance": "/v1/products/ZZZ-999"
}
```

One envelope, everywhere, means a client writes its error handling once. Designing
this shape *before* the handlers exist is what "contract first" means in practice.

| `type` suffix        | Status | When |
|----------------------|--------|------|
| `validation-failed`  | 400    | Malformed body, empty `items`, `qty` < 1 |
| `product-not-found`  | 404    | Unknown sku, on browse or at checkout |
| `order-not-found`    | 404    | Unknown order id |
| `insufficient-stock` | 409    | Not enough stock to satisfy a line |
| `order-not-cancellable` | 409 | Cancelling an already-cancelled order |
| `payment-declined`   | 402    | The card provider said no |

The 4xx/5xx split is a blame assignment: **4xx means the caller should change the
request, 5xx means it should not.** 409 is the interesting one — asking to cancel an
already-cancelled order is neither a malformed request nor a server bug, it is a
state conflict.

---

## `GET /health`

```json
{ "status": "ok", "implementation": "python" }
```

`200` always, no dependencies checked. The platform probes this; Session 3 explains
why the naive version of this endpoint causes outages.

## `GET /v1/products`

Query: `limit` (1–100, default 20), `cursor` (opaque, from `next_cursor`).

```json
{
  "items": [
    { "sku": "BNS-005", "name": "Single Origin Beans", "price_cents": 1800, "stock": 500 }
  ],
  "next_cursor": "FLT-006"
}
```

`next_cursor` is `null` on the last page. It is a **cursor**, not an offset —
offsets drift and repeat rows when someone inserts a product while a client pages.

## `GET /v1/products/{sku}`

`200` with a single product object, or `404` `product-not-found`.

## `POST /v1/orders`

```json
{ "items": [ { "sku": "GRD-002", "qty": 1 }, { "sku": "BNS-005", "qty": 2 } ] }
```

`201 Created`, `Location: /v1/orders/{id}`:

```json
{
  "id": "3f1b...",
  "status": "CONFIRMED",
  "total_cents": 22500,
  "created_at": "2026-08-12T18:30:00Z",
  "lines": [
    { "sku": "GRD-002", "name": "Burr Grinder",        "unit_cents": 18900, "qty": 1 },
    { "sku": "BNS-005", "name": "Single Origin Beans", "unit_cents": 1800,  "qty": 2 }
  ],
  "payment": { "status": "APPROVED", "auth_code": "AUTH-9C2A41B7" }
}
```

The whole thing is **one transaction**: reserve stock, write the order, charge the
card. Any failure rolls back all of it. Order a `ROA-008` to see a `402` where the
stock is left untouched.

Note what is *missing*: no `Idempotency-Key`. Retry this call twice here and you get
two orders — but nothing retries it, because an in-process call either returns or
throws. Session 2 adds the header, Session 3 explains why it becomes mandatory the
moment this is a network hop.

## `GET /v1/orders/{id}`

`200` with the order object above, or `404` `order-not-found`.

## `POST /v1/orders/{id}/cancel`

`200` with the order, `status` now `CANCELLED`, and the stock returned to the
catalog. `404` if unknown, `409` `order-not-cancellable` if already cancelled.

---

## Configuration

Twelve-factor: the same artifact runs anywhere, only the environment changes. Every
implementation reads exactly these, with these defaults.

| Variable | Default | Meaning |
|----------|---------|---------|
| `PORT` | `8080` | HTTP port |
| `DATABASE_PATH` | `./store.db` | SQLite file |
| `SCHEMA_PATH` | `../../db/schema.sql` | DDL, applied at boot |
| `SEED_PATH` | `../../db/seed.sql` | Seed data, applied at boot |
| `RESET_DB` | `true` | Delete the database file at boot, for reproducible demos |
| `PAYMENT_DECLINE_OVER_CENTS` | `500000` | Charges above this are declined |
| `PAYMENT_ALWAYS_DECLINE` | `false` | Force every charge to decline |

The payment stub is **deterministic on purpose**. A demo that fails randomly teaches
nothing; a demo that fails on command teaches exactly one thing at a time.
