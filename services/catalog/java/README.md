# catalog — Java (Spring Boot + JdbcTemplate)

The simplest service in the system, and the one to read first. Three endpoints, one
table, one file.

```bash
cd services && CATALOG_IMPL=java docker compose up --build catalog
curl localhost:8000/v1/products
```

## Read `pom.xml` against `services/orders/java/pom.xml`

That comparison is the fastest summary of the difference between the two services.

No gRPC, no protobuf, no protoc plugin, no `os-maven-plugin` extension to detect the
host platform, no `compile-custom` goal. Two starters and a driver, because a service
that only reads and is only called over HTTP needs nothing else.

Then open `monolith/java/.../catalog/CatalogService.java`. The SQL is the same. What
changed is everything around it:

| Monolith | Service |
|---|---|
| A `@Service` in a shared context | Its own process, its own image, its own release |
| A table in the one database | Its own Postgres, its own credentials |
| `catalog.reserve(sku, qty)` | **Gone.** Nothing here writes |
| Called by a method call | Called over HTTP, by someone who can time out |

Stock is still a column, still reported, and nothing ever decrements it — because the
transaction that used to do so cannot span two databases. See the comment in
`services/db/catalog/01-schema.sql`.

## Two things worth pointing at

**`/health` does not touch the database.** It is tempting to run `SELECT 1` there.
Don't: if this endpoint failed whenever Postgres hiccupped, the platform would start
killing catalog pods during a database blip — removing capacity exactly when the system
can least spare it. Liveness answers "should I be restarted?", and only this process
knows.

**The 404 in `get` is the most consequential response here.** Orders turns it into a
designed order rejection, so it has to be unambiguous, name the missing sku, and never
arrive as a 500. A dependency that fails clearly is a dependency you can build on.

## Where Spring answers for you, and why that is a bug

`?limit=abc` never reaches the controller: Spring cannot bind it to an `int` and
produces a 400 with its own body shape. Right status, wrong envelope — and the contract
has exactly one error shape.

`ProblemAdvice` therefore handles `MethodArgumentTypeMismatchException` explicitly, and
`NoResourceFoundException` too. **This is the most common way an implementation drifts
from its spec**: not by getting an endpoint wrong, but by letting the framework answer
on a path nobody wrote by hand. The Python implementation shipped with exactly this bug
until the conformance suite caught it.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8000` | HTTP port |
| `DATABASE_URL` | `postgres://store:store@catalog-db:5432/catalog` | Its own database. Converted to a JDBC URL in `CatalogApplication`, so this service reads the same libpq-style variable as the other five |

Two variables. That is the entire configuration surface of a service that reads. Compare
with `services/orders`, which has seven — five of them about what to do when somebody
else fails.
