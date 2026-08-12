# The store — TypeScript (NestJS)

```bash
npm install && npm start                     # from this directory
python tools/smoke.py http://localhost:8080  # from the repo root
```

Needs Node 22.5+ for the built-in `node:sqlite`. Or, with only Docker, from the repo
root: `MONOLITH_IMPL=typescript docker compose up --build`

## Files

| File | What it is |
|------|-----------|
| `src/config.ts` | Every setting, read from the environment |
| `src/errors.ts` | Domain outcomes — the failures the business decided can happen |
| `src/database.ts` | The one connection, and `transaction()` |
| `src/catalog/` | **MODULE.** Owns `products` |
| `src/payments/` | **MODULE.** Owns `payments`. No controller of its own |
| `src/orders/` | **MODULE.** Owns `orders` + `order_lines`. The orchestrator |
| `src/problem.filter.ts` | The one place a domain outcome becomes a status code |

## What is idiomatic here

**This is the clearest module boundary of the six.** `catalog.module.ts` has an
`exports: [CatalogService]` array — that array *is* the module's public API, and Nest
refuses to inject a provider its owning module did not export. Delete that one line and
`OrdersService` stops working. No other implementation here makes the boundary a thing
you can point at.

Then look at `orders.module.ts`: its `imports` array is the architecture diagram written
down. Orders depends on catalog and payments; neither depends on orders, and neither
depends on the other. That acyclic shape is what makes the three splittable in Session 3
— a cycle would mean two services that can never deploy independently, which means they
were never two services.

**`node:sqlite` ships inside Node.** No native module to compile, no dependency to
audit. It prints an experimental warning at boot; that is Node being honest, not a
misconfiguration.

**The database is `@Global`.** One line in `app.module.ts`, and it is the architectural
decision this whole bootcamp interrogates: it is what makes the transaction in
`OrdersService` possible, and precisely what Session 3 takes away.
