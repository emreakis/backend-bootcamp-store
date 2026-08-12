# catalog — Go (net/http + pgx)

The simplest service in the system, and the one to read first. Three endpoints, one
table, one file.

```bash
cd services && CATALOG_IMPL=go docker compose up --build catalog
curl localhost:8000/v1/products
```

No web framework. `net/http` has had method-aware routing and path wildcards since Go
1.22, so `GET /v1/products/{sku}` and `r.PathValue("sku")` are the standard library and
nothing else.

## Read it against the monolith

Open `monolith/go/internal/catalog/` next to `main.go` here. The SQL is the same. What
changed is everything around it:

| Monolith | Service |
|---|---|
| A package in a shared binary | Its own process, its own image, its own release |
| A table in the one database | Its own Postgres, its own credentials |
| `catalog.Reserve(tx, sku, qty)` | **Gone.** Nothing here writes |
| Called by a function call | Called over HTTP, by someone who can time out |

That third row is the interesting one. Stock is still a column, still reported, and
nothing ever decrements it — because the transaction that used to do so cannot span two
databases. See the comment in `services/db/catalog/01-schema.sql`.

## Three things worth pointing at

**`/health` does not touch the database.** It is tempting to run `SELECT 1` there.
Don't: if this endpoint failed whenever Postgres hiccupped, the platform would start
killing catalog pods during a database blip — removing capacity exactly when the system
can least spare it. Liveness answers "should I be restarted?", and only this process
knows.

**The 404 in `getProduct` is the most consequential response here.** Orders turns it
into a designed order rejection, so it has to be unambiguous, name the missing sku, and
never arrive as a 500. A dependency that fails clearly is a dependency you can build on.

**`items` is `[]product{}`, and `next_cursor` is a `*string`.** `json.Marshal` writes a
nil slice as `null` and an empty string as `""`, and the contract says `items` is an
array and `next_cursor` is `null` on the last page. Go is the language where both of
those go wrong by default, silently, and where a client paginating forever is the first
symptom. The conformance suite checks both.

## The validation nobody does for you

`?limit=abc` and `?limit=0` are both 400s carrying the usual problem envelope, and
`net/http` hands you a string and an opinion. That is honest: every framework in this
repo has a different default here — FastAPI's was a 422 with pydantic's own error
structure until the conformance suite caught it — and every default is wrong until
somebody checks it against the spec.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8000` | HTTP port |
| `DATABASE_URL` | `postgres://store:store@catalog-db:5432/catalog` | Its own database, nobody else's |

Two variables. That is the entire configuration surface of a service that reads. Compare
with `services/orders`, which has seven — five of them about what to do when somebody
else fails.
