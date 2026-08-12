# orders — Python (FastAPI + grpcio)

The orchestrator. REST at the edge, gRPC inside, two databases it cannot join across,
and the only service in this system that can be woken up by somebody else's outage.

```bash
cd services && ORDERS_IMPL=python docker compose up --build
curl -X POST localhost:8080/v1/orders -H 'content-type: application/json' \
     -H 'Idempotency-Key: my-key-1' \
     -d '{"items":[{"sku":"GRD-002","qty":1},{"sku":"BNS-005","qty":2}]}'
```

## The exercise lives in `app/payments_client.py`

Four `TODO (exercise 3.x)` blocks, in the order they matter:

| # | Where | What |
|---|-------|------|
| 3.1 | `payments_client.py` | **A deadline.** Do this one first; it is worth more than the other three together |
| 3.2 | `payments_client.py` | A bounded retry with backoff — legal only because `Charge` carries an idempotency key |
| 3.3 | `payments_client.py` | A circuit breaker, to stop calling and let payments recover |
| 3.4 | `catalog_client.py` | The same timeout problem, one hop earlier and much less dramatic |

Prove you need them before you write them:

```bash
PAYMENT_LATENCY_MS=30000 docker compose up -d payments   # SLOW
docker compose pause payments                            # BLACK HOLE
curl -X POST localhost:8080/v1/orders ... # hangs, both times
curl localhost:8080/health                # still {"status":"ok"} — healthy, and useless
```

Both hang, in every language, every time. A slow server accepts your connection and
then never answers; a **paused** one keeps its address and takes your SYN packets
without acknowledging them, which is what a crashed host or a network partition looks
like from the outside.

Now try the third one, `docker compose stop payments`, and watch it refuse to be one
behaviour. Measured on this stack with no deadline anywhere:

| orders | how long a stopped payments takes to fail |
|---|---|
| C# | ~4 s |
| Python, Go, Ruby | ~20 s — the gRPC library's own connect timeout |
| Java, TypeScript | still waiting after 25 s |

Same outage, same contract, four seconds to never. **That** is the argument for the
deadline: without one, how long your checkout hangs is a property of somebody else's
default rather than a number you chose. Twenty seconds is not "fast" for a checkout
either — it is a hang with extra steps.

Fix the deadline first, and all six agree.

The `solution` branch has all four filled in — `git diff main solution -- services/orders/python`.

### One Python-specific note on 3.4

`httpx` is one of very few HTTP clients that ships a *default* timeout (5 s). It has
been switched off explicitly in `catalog_client.py`, and the comment there says why:
partly so the exercise matches the other five languages, and partly because a library
default is not a policy. Five seconds is httpx's opinion; `CATALOG_TIMEOUT_MS` is your
statement about how long a checkout may spend pricing a line. Inheriting one when you
meant the other is how a service ends up with a latency budget nobody chose.

## Two things worth pointing at in this implementation

**The route handlers are `def`, not `async def`.** FastAPI runs a plain `def` in a
worker thread, which is what makes the blocking psycopg and blocking gRPC calls inside
them legal. Change one to `async def` without making everything underneath it async
too and a single slow charge blocks the event loop for *every* request in the process
— the same "one dependency takes the whole service down" failure this session is
about, arriving through a different door. Python makes that mistake unusually easy and
unusually cheap to make.

**There is no transaction around `service.checkout`.** Read the docstring; it is the
most important structural decision in this service.

Wrap the whole function in one connection, the way the monolith does, and you hold a
database connection open across two network calls. A slow payments service then does
not merely make checkout slow — it pins one connection per in-flight order until the
pool is empty (ten, here), at which point every other endpoint stops working too,
including the ones that never touch payments. You would have converted a payments
outage into a total outage, through your connection pool.

So: network first, holding nothing; then a short local transaction to write. The cost
is that the charge and the insert are no longer atomic together — if the process dies
between them, a customer is charged for an order that does not exist. That hole is
real, and the honest answers to it (an outbox, a reconciliation job) are the module
after this bootcamp. The monolith closed it with one keyword.

## Regenerating the contract

There is no generated code in this directory, and none in git. The Dockerfile runs
this before it copies a single line of our source:

```bash
python -m grpc_tools.protoc -I contracts/proto \
  --python_out=. --pyi_out=. --grpc_python_out=. \
  bootcamp/payments/v1/payments.proto
```

The generated package lands at `bootcamp/payments/v1/` because that is the path the
`.proto` was found at relative to `-I`. protoc derives module names from paths, so the
directory layout in `contracts/proto` *is* the namespace — which is why the file lives
three directories deep instead of being called `payments.v1.proto`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | HTTP port |
| `DATABASE_URL` | — | Its own database |
| `CATALOG_URL` | `http://catalog:8000` | A service name, resolved by the platform |
| `PAYMENTS_ADDR` | `payments:50051` | Likewise |
| `CATALOG_TIMEOUT_MS` | `1000` | exercise 3.4 |
| `PAYMENTS_TIMEOUT_MS` | `2000` | exercise 3.1 — policy, not a guess |
| `PAYMENTS_RETRY_MAX` | `2` | exercise 3.2 |
| `BREAKER_FAILURE_THRESHOLD` / `BREAKER_RESET_MS` | `5` / `10000` | exercise 3.3 |

Seven variables, five of them about what to do when somebody else fails. Catalog has
two. That ratio is the price of being the service in the middle.
