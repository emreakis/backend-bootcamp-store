# catalog — C# (ASP.NET Core minimal APIs + Npgsql)

The simplest service in the system, and the one to read first. Three endpoints, one
table, one file.

```bash
cd services && CATALOG_IMPL=csharp docker compose up --build catalog
curl localhost:8000/v1/products
```

## Read `Catalog.csproj` against `services/orders/csharp/Orders.csproj`

That comparison is the fastest summary of the difference between the two services.

No `Grpc.Net.Client`, no `Google.Protobuf`, no `Grpc.Tools`, and no `<Protobuf>` item
running a code generator during compilation. One package, because a service that only
reads and is only called over HTTP needs nothing else.

Then open `monolith/csharp/Catalog/`. The SQL is the same. What changed is everything
around it:

| Monolith | Service |
|---|---|
| A class in a shared assembly | Its own process, its own image, its own release |
| A table in the one database | Its own Postgres, its own credentials |
| `Catalog.Reserve(tx, sku, qty)` | **Gone.** Nothing here writes |
| Called by a method call | Called over HTTP, by someone who can time out |

Stock is still a column, still reported, and nothing ever decrements it — because the
transaction that used to do so cannot span two databases. See the comment in
`services/db/catalog/01-schema.sql`.

## Two things worth pointing at

**`/health` does not touch the database.** It is tempting to add a health check that
does. Don't: if this endpoint failed whenever Postgres hiccupped, the platform would
start killing catalog pods during a database blip — removing capacity exactly when the
system can least spare it. Liveness answers "should I be restarted?", and only this
process knows.

**`DATABASE_URL` is parsed rather than passed through.** Every service in this repo
reads one variable in the same libpq URI form, because that is what compose, Heroku and
Kubernetes secrets all hand you. Npgsql wants key/value pairs, so the translation
happens once at the boundary rather than forcing the deployment to speak .NET's dialect.
The Java implementation does the same for JDBC. Twelve-factor config is not "read
strings from the environment" — it is "accept what the platform actually gives you".

## Why `limit` is read as a raw string

Binding `int limit` as a minimal-API parameter would let ASP.NET answer `?limit=abc`
with its own 400 body — right status, wrong shape, on a path nobody wrote by hand. The
contract has exactly one error envelope, so the parse and the range check happen
explicitly.

**This is the most common way an implementation drifts from its spec.** The Python
implementation shipped with exactly this bug — FastAPI's 422 carrying pydantic's error
structure — until the conformance suite caught it.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8000` | HTTP port |
| `DATABASE_URL` | `postgres://store:store@catalog-db:5432/catalog` | Its own database, nobody else's |

Two variables. That is the entire configuration surface of a service that reads. Compare
with `services/orders`, which has seven — five of them about what to do when somebody
else fails.
