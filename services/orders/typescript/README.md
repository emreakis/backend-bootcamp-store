# orders — TypeScript (NestJS + grpc-js)

The orchestrator. REST at the edge, gRPC inside, two databases it cannot join across,
and the only service in this system that can be woken up by somebody else's outage.

```bash
cd services && ORDERS_IMPL=typescript docker compose up --build
curl -X POST localhost:8080/v1/orders -H 'content-type: application/json' \
     -H 'Idempotency-Key: my-key-1' \
     -d '{"items":[{"sku":"GRD-002","qty":1},{"sku":"BNS-005","qty":2}]}'
```

## The exercise lives in `src/payments.client.ts`

Four `TODO (exercise 3.x)` blocks, in the order they matter:

| # | Where | What |
|---|-------|------|
| 3.1 | `payments.client.ts` | **A deadline.** Do this one first; it is worth more than the other three together |
| 3.2 | `payments.client.ts` | A bounded retry with backoff — legal only because `Charge` carries an idempotency key |
| 3.3 | `payments.client.ts` | A circuit breaker, to stop calling and let payments recover |
| 3.4 | `catalog.client.ts` | The same timeout problem, one hop earlier and much less dramatic |

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

The `solution` branch has all four filled in — `git diff main solution -- services/orders/typescript`.

### The Node-specific lesson: a deadline is a *moment*

grpc-js wants `deadline: Date.now() + timeoutMs` — an absolute point in time, not a
duration. Python takes `timeout=2.0` and Go takes `context.WithTimeout(ctx, 2*time.Second)`,
and both immediately convert what you gave them into an instant. Node just shows you
the instant.

That matters as soon as you add exercise 3.2. Compute the deadline **once, outside the
retry loop** and all three attempts share a single 2-second budget. Recompute it inside
the loop and each attempt gets its own, turning a 2-second promise into a 6-second one.
Both are defensible; only one of them is what you meant.

### And the Node-specific failure mode

There is no thread pool here to exhaust. When payments hangs, the symptom is not "the
pool is full" — it is memory quietly filling with pending promises while the process
keeps reporting itself healthy and keeps accepting new work. That is worse than
running out of threads, because running out of threads is at least loud.

## `orders.service.ts` — two things worth reading closely

**There is no transaction around `checkout`.** Take a connection at the top and hold it
to the bottom, the way the monolith does, and a slow payments service pins one
connection per in-flight order until the pool is empty (ten, here), at which point every
other endpoint stops working too — including the ones that never touch payments. You
would have converted a payments outage into a total outage, through your connection
pool.

So: network first, holding nothing; then a short local transaction. The cost is that
the charge and the insert are no longer atomic together — if the process dies between
them, a customer is charged for an order that does not exist. That hole is real, and
the honest answers to it (an outbox, a reconciliation job) are the module after this
bootcamp.

**The catalog calls are sequential, not `Promise.all`.** Pricing three lines in
parallel would be faster and would also triple the burst this service puts on catalog
for a single checkout. The first thing a struggling dependency needs is *fewer*
concurrent requests. Parallelism is a decision, not a default — and this is one of the
few places where the JavaScript idiom pushes you towards the wrong one.

## Regenerating the contract

There is no generated code in this repository, and none in git. The Dockerfile runs
this before `tsc` ever sees `src/`:

```bash
protoc -I contracts/proto \
  --plugin=./node_modules/.bin/protoc-gen-ts_proto \
  --ts_proto_out=./src/gen \
  --ts_proto_opt=outputServices=grpc-js,esModuleInterop=true \
  bootcamp/payments/v1/payments.proto
```

ts-proto is a protoc plugin like any other — the same `protoc` that produces Go code
for the payments service, pointed at a different back end.

**Why not `@grpc/proto-loader`?** Because it reads the `.proto` at *runtime* and hands
you `any`. It works, it is the more common Node habit, and it moves every contract
mismatch from build time to 3am. Generating is the same choice Java, Go and C# make in
this repo, and it is what makes "delete a field from the proto and the build stops" a
true sentence here too.

One thing this cost, and it is worth knowing: `ts-proto` is a devDependency because it
only runs at build time, but the code it *emits* imports `@bufbuild/protobuf/wire` on
every call. That has to be a runtime dependency. Generated code drags its runtime along
— the same lesson the Java service learned more loudly, where a protoc/protobuf-java
mismatch fails at compile time instead of at startup.

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
