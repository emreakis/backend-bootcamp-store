# The store — Java (Spring Boot)

```bash
mvn spring-boot:run                          # from this directory
python tools/smoke.py http://localhost:8080  # from the repo root
```

Or without installing anything but Docker, from the repo root:
`MONOLITH_IMPL=java docker compose up --build`

## Files

| File | What it is |
|------|-----------|
| `application.properties` | Every setting, read from the environment |
| `DomainException.java` | Domain outcomes — the failures the business decided can happen |
| `catalog/CatalogService.java` | **MODULE.** Owns `products` |
| `payments/PaymentsService.java` | **MODULE.** Owns `payments`. No controller of its own |
| `orders/OrdersService.java` | **MODULE.** Owns `orders` + `order_lines`. The orchestrator |
| `ProblemAdvice.java` | The one place a domain outcome becomes a status code |

## What is idiomatic here

**`@Transactional` is the whole lesson in one annotation.** It opens a transaction,
binds its connection to the thread, and every statement any module runs from there joins
it. Nothing in `CatalogService.reserve` mentions a transaction — it does not have to.

That is exactly what makes it dangerous. The atomicity that `checkout` depends on is
invisible at the call site, so when `catalog` becomes a service in Session 3, nothing in
the code changes colour to warn you that the guarantee is gone.

**`ProblemDetail` ships with Spring.** RFC 9457 is not something this project invented —
return one from an `@ExceptionHandler` and the framework sets
`application/problem+json` for you. Compare `ProblemAdvice.java` with the hand-built
equivalents in Go and TypeScript.

**One line handles the naming mismatch.** `spring.jackson.property-naming-strategy=SNAKE_CASE`
turns `priceCents` into `price_cents` everywhere, so no record needs a `@JsonProperty`.

**`spring-boot-starter-jdbc`, not JPA.** Every implementation in this repo writes raw
SQL, so the six can be read side by side without also teaching six different ORMs.

**Package-private by default.** `CatalogController`, `ProblemAdvice` and every
constructor are package-private; only each module's service is `public`. That is the
module boundary, enforced by the compiler.
