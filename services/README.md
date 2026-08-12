# Services — Session 3

Empty on purpose. This is where the monolith comes apart.

On Saturday afternoon the three modules you read in Session 1 become three services:

```
                      REST                        gRPC
   client ──────► orders ──────► catalog     orders ──────► payments
                    │                                          │
              orders-db                                  (card provider)
                                 catalog-db
```

- **catalog** — REST, its own database. The simplest service in the system.
- **orders** — REST at the edge, a gRPC client inside. The orchestrator, and the one
  that pages you at 3am.
- **payments** — gRPC only. Nothing outside the system ever calls it directly, which is
  exactly why it does not need REST.

Every service will be implemented in all six languages again, and because each one is a
container behind a fixed contract, any combination boots:

```bash
CATALOG_IMPL=go ORDERS_IMPL=csharp PAYMENTS_IMPL=ruby docker compose up
```

## What breaks

The exercise is not building it. It is breaking it:

```bash
docker compose stop payments
```

Then watch `orders` — a healthy service — die of somebody else's outage, because every
checkout thread is blocked on a call that will never return. Fixing that with a timeout,
a bounded retry and a circuit breaker is the last hour of the bootcamp.

The `main` branch will ship the system with those three defences left as marked `TODO`s;
the `solution` branch fills them in. `git diff main solution -- services/orders/go` is
the lesson, in whichever language you asked for.

## The test that stops passing

`tools/smoke.py` has two checks tagged `ATOMICITY`. They pass against all six monoliths
today, because a declined payment rolls the whole checkout back and the reserved stock
returns by itself.

Run them against the three services and they fail. Nothing rolls back across three
databases. Making them pass again — with a saga and a compensating action that survives
a crash between two calls — is what "microservices are a trade, not an upgrade" means in
code.
