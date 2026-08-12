# Services — Session 3

Empty on purpose. This is where the monolith comes apart.

On Saturday afternoon the three modules you read in Session 1 become three services:

```
                REST                                   gRPC
  client ────► orders ──────► catalog          orders ──────► payments
                 │              │                                │
            orders-db      catalog-db                   (stubbed card provider,
                                                            no database)
```

- **catalog** — REST, its own database, **read-only**. The simplest service in the
  system, small enough to read in full.
- **orders** — REST at the edge, a gRPC client inside. The orchestrator, and the one
  that pages you at 3am.
- **payments** — gRPC only, no database. Nothing outside the system ever calls it
  directly, which is exactly why it does not need REST.

Every service is implemented in all six languages, and because each one is a container
behind a fixed contract, any combination boots:

```bash
CATALOG_IMPL=go ORDERS_IMPL=csharp PAYMENTS_IMPL=ruby docker compose up
```

Swapping catalog's language while orders keeps running is thirty seconds of demo that
argues "smart endpoints, dumb pipes" better than any slide.

## What we deliberately did not build

The monolith reserves stock inside the checkout transaction. **The services do not
touch stock at all** — orders asks catalog for a price and nothing else.

That is not a shortcut we are hiding. It is the first real design decision the split
forces, and the honest answer for most teams: *when a transaction would have to span
two services, the cheapest correct move is to stop needing it.* Buying that guarantee
back across a network needs a saga, a compensating action that survives a crash between
two calls, and reservations that expire when no confirmation arrives — a module's worth
of machinery to replace one `ROLLBACK`.

Inventory, confirmation emails and analytics all belong to the same pattern: work that
should happen *after* the charge, over a broker, rather than keeping a customer waiting.
That is the module after this bootcamp, not a gap in it.

The two `ATOMICITY` checks in `tools/smoke.py` therefore have no counterpart in the
services conformance suite. Notice the absence. It cost something.

## What breaks — the Session 3 exercise

The thing that *does* go wrong here is availability, and it goes wrong quietly:

```bash
docker compose stop payments
```

Then watch `orders` — a completely healthy service — die of somebody else's outage.
Every checkout thread blocks on a call that will never return, the pool drains, the
queue grows, and a payments outage has become a store outage. That is *the network is
reliable* collecting its debt.

Fixing it, in order of importance:

1. **A deadline.** The default of *forever* is the worst possible value.
2. **A bounded retry** — only because `Charge` carries an idempotency key and is safe
   to repeat. Backoff and a budget, because retrying into an overloaded service is how
   you turn a brownout into an outage.
3. **A circuit breaker**, which converts a hang into a fast, designed failure and gives
   payments room to recover.

`main` ships the system with those three left as marked `TODO`s in the orders service's
payments client. The `solution` branch fills them in, so

```bash
git diff main solution -- services/orders/go
```

is the lesson, in whichever language the room asks for.

## The tests that matter here

`conformance/` runs the contracts in `../contracts/` against whatever is running, plus a
class of checks the monolith could never have needed:

| Tag | Asserts |
|-----|---------|
| `CONTRACT` | Every response matches the OpenAPI and proto definitions |
| `RESILIENCE` | With payments stopped, checkout fails **fast** and says so — and `/health` still returns 200, because orders is not sick, its dependency is |

That second row is the whole session. A distributed system that fails loudly is a
system you can operate; one that fails quietly, one hung thread at a time, is not.
