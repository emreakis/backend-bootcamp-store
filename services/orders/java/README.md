# orders — Java (Spring Boot + grpc-java)

The orchestrator. REST at the edge, gRPC inside, two databases it cannot join across,
and the only service in this system that can be woken up by somebody else's outage.

```bash
cd services && docker compose up --build
curl -X POST localhost:8080/v1/orders -H 'content-type: application/json' \
     -H 'Idempotency-Key: my-key-1' \
     -d '{"items":[{"sku":"GRD-002","qty":1},{"sku":"BNS-005","qty":2}]}'
```

## The exercise lives in `PaymentsClient.java`

Four `TODO (exercise 3.x)` blocks, in the order they matter:

| # | Where | What |
|---|-------|------|
| 3.1 | `PaymentsClient` | **A deadline.** Do this one first; it is worth more than the other three together |
| 3.2 | `PaymentsClient` | A bounded retry with backoff — legal only because `Charge` carries an idempotency key |
| 3.3 | `PaymentsClient` | A circuit breaker, to stop calling and let payments recover |
| 3.4 | `CatalogClient` | The same timeout problem, one hop earlier and much less dramatic |

Prove you need them before you write them:

```bash
docker compose stop payments                              # payments is DOWN
PAYMENT_LATENCY_MS=30000 docker compose up -d payments    # payments is SLOW
curl -X POST localhost:8080/v1/orders ... # hangs, both times
curl localhost:8080/health                # still {"status":"ok"} — healthy, and useless
```

Both hang, and the first is the surprise: on a container network a stopped server does
not refuse connections, it swallows them, so the connect waits out a TCP timeout
measured in minutes. **To a caller with no deadline, "down" and "slow" are the same
thing.** Fix the deadline first; only then does the difference start to matter.

The `solution` branch has all four filled in — `git diff main solution -- services/orders/java`.

## Read `OrdersService.checkout` for what is NOT there

There is no `@Transactional` on it, and that is the most important structural decision
in this service.

Annotate the whole method, the way the monolith does, and you hold a database
connection open across two network calls. A slow payments service then does not merely
make checkout slow — it pins one connection per in-flight order until the pool is
empty, at which point every other endpoint stops working too, including the ones that
never touch payments. You would have converted a payments outage into a total outage,
through your connection pool.

So: network first, holding nothing; then a short local transaction to write. The cost
is that the charge and the insert are no longer atomic together — if the process dies
between them, a customer is charged for an order that does not exist. That hole is
real, and the honest answers to it (an outbox, a reconciliation job) are the module
after this bootcamp. The monolith closed it with one keyword.

## Two bugs this code already had, left documented

**`RestClient.builder()` vs the injected `RestClient.Builder`.** The static factory
builds a client with a default `ObjectMapper` that has never heard of the `SNAKE_CASE`
strategy in `application.properties`. `price_cents` then quietly fails to bind to
`priceCents`, every price arrives as `0`, and the first symptom is payments rejecting a
charge for nothing. A silent zero is the worst kind of deserialisation failure: it does
not throw, and it looks like a price.

**protoc and `protobuf-java` are one unit.** Build with protoc 4.31 against gRPC 1.73 —
which ships `protobuf-java` 3.25.5 — and you get `cannot find symbol: method
resolveAllFeaturesImmutable()`. Generated code calls into its runtime, and a newer
generator emits calls only a newer runtime has. Check with `mvn dependency:tree` before
changing either number. Every language with a protobuf plugin has this trap; Java just
reports it early and clearly.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | HTTP port |
| `DATABASE_URL` | — | Its own database. Converted to a JDBC URL in `OrdersApplication` |
| `CATALOG_URL` | `http://catalog:8000` | A service name, resolved by the platform |
| `PAYMENTS_ADDR` | `payments:50051` | Likewise |
| `CATALOG_TIMEOUT_MS` | `1000` | exercise 3.4 |
| `PAYMENTS_TIMEOUT_MS` | `2000` | exercise 3.1 — policy, not a guess |
| `PAYMENTS_RETRY_MAX` | `2` | exercise 3.2 |
| `BREAKER_FAILURE_THRESHOLD` / `BREAKER_RESET_MS` | `5` / `10000` | exercise 3.3 |

Seven variables, five of them about what to do when somebody else fails. Catalog has
two. That ratio is the price of being the service in the middle.
