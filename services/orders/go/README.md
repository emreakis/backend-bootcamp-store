# orders — Go (net/http + grpc-go)

> **You are on the `solution` branch.** The four `TODO (exercise 3.x)` blocks this
> page describes are already filled in here. See [SOLUTION.md](../../../SOLUTION.md), or
> `git diff main solution -- services/orders/go` for just this one.

The orchestrator. REST at the edge, gRPC inside, two databases it cannot join across,
and the only service in this system that can be woken up by somebody else's outage.

```bash
cd services && ORDERS_IMPL=go docker compose up --build
curl -X POST localhost:8080/v1/orders -H 'content-type: application/json' \
     -H 'Idempotency-Key: my-key-1' \
     -d '{"items":[{"sku":"GRD-002","qty":1},{"sku":"BNS-005","qty":2}]}'
```

No web framework. `net/http` has had method-aware routing and path wildcards since Go
1.22, so `POST /v1/orders` and `r.PathValue("id")` in `main.go` are the standard
library and nothing else.

## The exercise lives in `payments_client.go`

Four `TODO (exercise 3.x)` blocks, in the order they matter:

| # | Where | What |
|---|-------|------|
| 3.1 | `payments_client.go` | **A deadline.** Do this one first; it is worth more than the other three together |
| 3.2 | `payments_client.go` | A bounded retry with backoff — legal only because `Charge` carries an idempotency key |
| 3.3 | `payments_client.go` | A circuit breaker, to stop calling and let payments recover |
| 3.4 | `catalog_client.go` | The same timeout problem, one hop earlier and much less dramatic |

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

The `solution` branch has all four filled in — `git diff main solution -- services/orders/go`.

### Two things Go makes clearer than the other five

**The deadline is the context, not a client option.** `context.WithTimeout` is the
whole mechanism, it is the first argument to every generated method, and it is
impossible to make the call without passing *something*. That is the clearest
expression of the idea in any of the six languages: a deadline belongs to the request
you are making right now, not to the connection you happen to be making it over. The
cost is that `context.Background()` is always right there, one word away, and it means
*forever*.

**`grpc.NewClient` does not dial.** It is lazy; the first RPC is what connects. During
this exercise that matters: a client that constructs without error tells you nothing at
all about whether payments exists.

## `service.go` — read what is NOT there

There is no transaction around `checkout`, and that is the most important structural
decision in this service.

`Begin()` at the top and `Commit()` at the bottom, the way the monolith does, and you
hold a database connection open across two network calls. A slow payments service then
does not merely make checkout slow — it pins one connection per in-flight order until
the pool is empty, at which point every other endpoint stops working too, including the
ones that never touch payments. You would have converted a payments outage into a total
outage, through your connection pool.

So: network first, holding nothing; then a short local transaction to write. The cost
is that the charge and the insert are no longer atomic together — if the process dies
between them, a customer is charged for an order that does not exist. That hole is
real, and the honest answers to it (an outbox, a reconciliation job) are the module
after this bootcamp. The monolith closed it with one keyword.

## Two footguns this code is written around

**`Qty` is a `*int64`.** Go zeroes missing JSON fields, so an absent `qty` and an
explicit `"qty": 0` are indistinguishable in a plain `int64`. The pointer is how you get
field presence back — the same problem proto3 solves with `optional`, met here in a
different language on the same afternoon.

**`Lines` is initialised to `[]orderLine{}`, never left nil.** `json.Marshal` writes a
nil slice as `null`, and the contract says `lines` is an array. Six languages, six
different ways to get that subtly wrong; the conformance suite catches all of them.

## Regenerating the contract

There is no generated code in this directory, and none in git. The Dockerfile runs this
before it copies a single line of our source:

```bash
protoc -I contracts/proto \
  --go_out=. --go_opt=module=github.com/backendguru/store \
  --go-grpc_out=. --go-grpc_opt=module=github.com/backendguru/store \
  bootcamp/payments/v1/payments.proto
```

That is the *identical* command the payments service runs, and `go.mod` declares the
same module path for the same reason: both sides of the contract import the identical
generated package because both were produced from the identical bytes.

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
