# catalog — Ruby (Sinatra + pg)

The simplest service in the system, and the one to read first. Three endpoints, one
table, one file.

```bash
cd services && CATALOG_IMPL=ruby docker compose up --build catalog
curl localhost:8000/v1/products
```

## Read it against the monolith

Open `monolith/ruby/lib/catalog.rb` next to `app.rb` here. The SQL is the same. What
changed is everything around it:

| Monolith | Service |
|---|---|
| A module in a shared process | Its own process, its own image, its own release |
| A table in the one database | Its own Postgres, its own credentials |
| `Catalog.reserve(db, sku, qty)` | **Gone.** Nothing here writes |
| Called by a method call | Called over HTTP, by someone who can time out |

Stock is still a column, still reported, and nothing ever decrements it — because the
transaction that used to do so cannot span two databases. See the comment in
`services/db/catalog/01-schema.sql`.

The `Gemfile` is the other half of the comparison: no `grpc`, no `grpc-tools`, because a
service that only reads and is only called over HTTP needs neither.

## Three things worth pointing at

**`/health` does not touch the database.** It is tempting to run `SELECT 1` there.
Don't: if this endpoint failed whenever Postgres hiccupped, the platform would start
killing catalog pods during a database blip — removing capacity exactly when the system
can least spare it.

**`Thread.current[:pg] ||= PG.connect(...)` is the connection pool.** puma serves this
app from a thread pool and a `PG::Connection` is not safe to share across threads, so
each one gets its own. Crude next to the managed pools the other five implementations
get for free — and *visible*, which is the point. Something has to answer "how many
connections does this process hold open", and if you do not answer it, your framework
answered it for you.

**`row['price_cents'].to_i` is not decoration.** Postgres hands everything back as a
string, `BIGINT` included. Ship these without the conversion and a client that expected
a number gets `"18900"`. Ruby will happily compare a string to a number and be wrong
about it, quietly, in an afternoon nobody enjoys.

## The validation Sinatra does not do

`?limit=abc` and `?limit=0` are both 400s carrying the usual problem envelope, checked
by hand — `Integer(raw, exception: false)` and a `between?`. Sinatra hands every
parameter over as a string with no opinion about its range.

That is honest, and it is also the trap: every framework in this repo has a different
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
