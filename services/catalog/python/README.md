# catalog — Python (FastAPI)

The simplest service in the system, and the one to read first. Three endpoints, one
table, one file of logic.

```bash
cd services && CATALOG_IMPL=python docker compose up --build catalog
curl localhost:8000/v1/products
```

## Read it against the monolith

Open `monolith/python/app/catalog.py` next to `app/main.py` here. The SQL is the same.
What changed is everything around it:

| Monolith | Service |
|---|---|
| A module in a shared process | Its own process, its own image, its own release |
| A table in the one database | Its own Postgres, its own credentials |
| `catalog.reserve(conn, sku, qty)` | **Gone.** Nothing here writes |
| Called by a function call | Called over HTTP, by someone who can time out |

That third row is the interesting one. Stock is still a column, still reported, and
nothing ever decrements it — because the transaction that used to do so cannot span two
databases. See the comment in `services/db/catalog/01-schema.sql`.

## Two things worth pointing at

**`/health` does not touch the database.** It is tempting to run `SELECT 1` there. Don't:
if this endpoint failed whenever Postgres hiccupped, the platform would start killing
catalog pods during a database blip — removing capacity exactly when the system can
least spare it. Liveness answers "should I be restarted?", and only this process knows.

**The 404 in `get_product` is the most consequential response here.** Orders turns it
into a designed order rejection, so it has to be unambiguous, name the missing sku, and
never arrive as a 500. A dependency that fails clearly is a dependency you can build on.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8000` | HTTP port |
| `DATABASE_URL` | `postgres://store:store@catalog-db:5432/catalog` | Its own database, nobody else's |

Two variables. That is the entire configuration surface of a service that reads.
Compare with `services/orders`, which has seven — five of them about what to do when
somebody else fails.
