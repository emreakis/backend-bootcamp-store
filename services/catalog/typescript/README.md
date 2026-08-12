# catalog — TypeScript (NestJS + node-postgres)

The simplest service in the system, and the one to read first. Three endpoints, one
table, one file — the whole service is `src/main.ts`, which is itself the point.

```bash
cd services && CATALOG_IMPL=typescript docker compose up --build catalog
curl localhost:8000/v1/products
```

## Read it against the monolith

Open `monolith/typescript/src/catalog/` next to this. The SQL is the same. What changed
is everything around it:

| Monolith | Service |
|---|---|
| Three files and a `CatalogModule` | One file, because there is nothing left to modularise |
| A table in the one database | Its own Postgres, its own credentials |
| `catalog.reserve(sku, qty)` | **Gone.** Nothing here writes |
| Injected into `OrdersService` | Called over HTTP, by someone who can time out |

That second row is worth a minute. The monolith needed a module boundary because three
modules shared one process; here the process *is* the boundary, and a module system
inside it would be ceremony. Not every service earns the structure its monolith had.

Stock is still a column, still reported, and nothing ever decrements it — because the
transaction that used to do so cannot span two databases. See the comment in
`services/db/catalog/01-schema.sql`.

## Two things worth pointing at

**`/health` does not touch the database.** It is tempting to run `SELECT 1` there.
Don't: if this endpoint failed whenever Postgres hiccupped, the platform would start
killing catalog pods during a database blip — removing capacity exactly when the system
can least spare it.

**`toProduct` calls `Number()` on `price_cents` and `stock`, and that is not paranoia.**
node-postgres hands `BIGINT` back as a *string*, because a JS number stops being exact
past 2^53. Money in minor units will never come close, so the conversion is safe — but
forget it and this service ships `"price_cents": "18900"` to a client expecting a
number. The string is the driver being careful, not the driver being annoying.

## The validation Nest does not do

`?limit=abc` and `?limit=0` are both 400s carrying the usual problem envelope, checked
by hand in the controller. Nest hands query parameters over as strings and has no
opinion about their range unless you bring a validation pipe.

That is fine, and it is also the trap: every framework in this repo has a different
default here — FastAPI's was a 422 with pydantic's own error structure until the
conformance suite caught it — and every default is wrong until somebody checks it
against the spec.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8000` | HTTP port |
| `DATABASE_URL` | `postgres://store:store@catalog-db:5432/catalog` | Its own database, nobody else's |

Two variables. That is the entire configuration surface of a service that reads. Compare
with `services/orders`, which has seven — five of them about what to do when somebody
else fails.
