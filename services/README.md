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

The thing that *does* go wrong here is availability, and it goes wrong quietly. Three
ways to break payments, and they are not the same failure:

```bash
PAYMENT_LATENCY_MS=30000 docker compose up -d payments   # SLOW: accepts, then holds
docker compose pause payments                            # BLACK HOLE: packets vanish
docker compose stop payments                             # DOWN: it depends
```

The first two hang, in every language, every time. Watch `orders` — a completely
healthy service — die of somebody else's outage: every checkout blocks on a call that
will never return, the pool drains, the queue grows, and a payments outage has become a
store outage. That is *the network is reliable* collecting its debt.

The third is the one worth doing live, because it refuses to be one behaviour. Measured
across the six orders implementations, with no deadline anywhere:

| orders | how long a stopped payments takes to fail |
|---|---|
| C# | ~4 s |
| Python, Go, Ruby | ~20 s — the gRPC library's own connect timeout |
| Java, TypeScript | still waiting after 25 s |

Same outage, same contract, four seconds to never. **That is the argument for the
deadline**: without one, how long a checkout hangs is a property of somebody else's
library default rather than a number anybody chose. Twenty seconds is not "fast" for a
checkout either — it is a hang with extra steps.

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

```bash
python conformance/contract.py                    # 87 checks, HTTP only, stdlib only
python conformance/resilience.py                  # the STARTER behaviour
python conformance/resilience.py --expect-fixed   # the SOLUTION behaviour
```

| File | Asserts |
|-----|---------|
| `contract.py` | Every response matches the OpenAPI definitions, in any combination of the six languages. Payments is only ever reached *through* orders, because that is the only way anything in this store reaches it |
| `resilience.py` | By default, that a slow or black-holed payments **hangs** checkout while `/health` keeps answering `ok`. With `--expect-fixed`, that the same outage produces a fast `503` carrying `Retry-After`, and that the system recovers without restarting orders |

`resilience.py` is the exercise as a test, and it is worth noticing that its default
mode consists of passing assertions describing a broken system. That is an odd thing to
write down until you see the alternative: a broken system nobody wrote down. The four
`TODO` blocks are the diff between its two modes.

That second row is the whole session. A distributed system that fails loudly is a
system you can operate; one that fails quietly, one hung thread at a time, is not.
