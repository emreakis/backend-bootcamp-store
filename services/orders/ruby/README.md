# orders — Ruby (Sinatra + grpc)

The orchestrator. REST at the edge, gRPC inside, two databases it cannot join across,
and the only service in this system that can be woken up by somebody else's outage.

```bash
cd services && ORDERS_IMPL=ruby docker compose up --build
curl -X POST localhost:8080/v1/orders -H 'content-type: application/json' \
     -H 'Idempotency-Key: my-key-1' \
     -d '{"items":[{"sku":"GRD-002","qty":1},{"sku":"BNS-005","qty":2}]}'
```

## The exercise lives in `lib/payments_client.rb`

Four `TODO (exercise 3.x)` blocks, in the order they matter:

| # | Where | What |
|---|-------|------|
| 3.1 | `lib/payments_client.rb` | **A deadline.** Do this one first; it is worth more than the other three together |
| 3.2 | `lib/payments_client.rb` | A bounded retry with backoff — legal only because `Charge` carries an idempotency key |
| 3.3 | `lib/payments_client.rb` | A circuit breaker, to stop calling and let payments recover |
| 3.4 | `lib/catalog_client.rb` | The same timeout problem, one hop earlier and much less dramatic |

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

The `solution` branch has all four filled in — `git diff main solution -- services/orders/ruby`.

### The Ruby-specific lesson: two libraries, opposite rules

`lib/payments_client.rb` builds its gRPC stub **once** and shares it across every puma
thread. `lib/catalog_client.rb` builds a fresh `Net::HTTP` **per call** and explains why
in a comment: gRPC's channel is designed for concurrent use, and Ruby's standard HTTP
client is not thread-safe. Two clients in the same service, one shared and one not, and
the difference is not a style choice — it is what the libraries actually promise.

Guessing either way gets you a bug that only appears under load, which is the worst kind
to find.

The same theme runs through exercise 3.3. `Config::BREAKER_FAILURE_THRESHOLD` counts
failures across threads, so the counter wants a `Mutex`. MRI's GVL will hide most of the
races most of the time — which is worse than not hiding them.

And `Net::HTTP` makes you name **two** timeouts, `open_timeout` and `read_timeout`. That
split is the useful part: "I cannot reach this host" and "this host accepted my
connection and then went quiet" are different failures with different causes. Both start
at `nil` in the starter; Ruby actually defaults to 60 seconds each, switched off here so
the exercise matches the languages that genuinely wait forever, and because 60 seconds
is Ruby's opinion, not your latency budget.

## `lib/orders_service.rb` — read what is NOT there

There is no `connection.transaction` around `checkout`, and that is the most important
structural decision in this service.

Wrap the whole method the way the monolith does and you hold a database connection open
across two network calls. A slow payments service then does not merely make checkout
slow — it pins one connection per in-flight order until the pool is empty, at which
point every other endpoint stops working too, including the ones that never touch
payments. You would have converted a payments outage into a total outage, through your
connection pool.

So: network first, holding nothing; then a short local transaction to write. The cost is
that the charge and the insert are no longer atomic together — if the process dies
between them, a customer is charged for an order that does not exist. That hole is real,
and the honest answers to it (an outbox, a reconciliation job) are the module after this
bootcamp. The monolith closed it with one keyword.

Worth noticing in `lib/orders_repository.rb`: the connection pool here is
`Thread.current[:pg] ||= PG.connect(...)`. Crude next to the managed pools the other
five implementations get for free — and visible, which is the point. Something has to
answer "how many connections does this process hold open", and if you do not answer it,
your framework answered it for you.

## Regenerating the contract

There is no generated code in this repository, and none in git. The Dockerfile runs this
before it copies a single line of our source:

```bash
bundle exec grpc_tools_ruby_protoc -I contracts/proto \
  --ruby_out=gen --grpc_out=gen \
  bootcamp/payments/v1/payments.proto
```

`grpc-tools` ships its own protoc and its own Ruby plugin, so this is the same tool the
Go, TypeScript and C# images run — invoked through a wrapper script. Two files come out:
`_pb.rb` for the messages and `_services_pb.rb` for the service. That split is a
protobuf idea rather than a Ruby one; plenty of projects generate only the first half.

One wrinkle worth knowing, because it cost a build: `_services_pb.rb` contains
`require 'bootcamp/payments/v1/payments_pb'` — an **absolute** require, assuming the
generated tree is a load-path root the way a published gem would be. So
`require_relative` into it works for the first file and fails on the one it pulls in.
Hence the `$LOAD_PATH.unshift` at the top of `lib/payments_client.rb`.

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
