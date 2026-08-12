# orders — C# (ASP.NET Core minimal APIs + Grpc.Net.Client)

The orchestrator. REST at the edge, gRPC inside, two databases it cannot join across,
and the only service in this system that can be woken up by somebody else's outage.

```bash
cd services && ORDERS_IMPL=csharp docker compose up --build
curl -X POST localhost:8080/v1/orders -H 'content-type: application/json' \
     -H 'Idempotency-Key: my-key-1' \
     -d '{"items":[{"sku":"GRD-002","qty":1},{"sku":"BNS-005","qty":2}]}'
```

## The exercise lives in `PaymentsClient.cs`

Four `TODO (exercise 3.x)` blocks, in the order they matter:

| # | Where | What |
|---|-------|------|
| 3.1 | `PaymentsClient.cs` | **A deadline.** Do this one first; it is worth more than the other three together |
| 3.2 | `PaymentsClient.cs` | A bounded retry with backoff — legal only because `Charge` carries an idempotency key |
| 3.3 | `PaymentsClient.cs` | A circuit breaker, to stop calling and let payments recover |
| 3.4 | `CatalogClient.cs` | The same timeout problem, one hop earlier and much less dramatic |

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

The `solution` branch has all four filled in — `git diff main solution -- services/orders/csharp`.

### Two .NET-specific traps in these exercises

**`DateTime.UtcNow`, not `DateTime.Now`.** Grpc.Net throws if you hand it a deadline
whose `Kind` is not UTC. That is the library refusing to guess rather than being fussy:
the deadline goes on the wire as an instant, and an instant in an unspecified timezone
is not one.

**A timeout arrives as `TaskCanceledException`, not `TimeoutException`.** Catch only
`HttpRequestException` in `CatalogClient` and your carefully written timeout handling
silently never runs — the request fails, and it fails as a 500 rather than the 503 you
designed. The `when (... is HttpRequestException or TaskCanceledException)` filter in
that file is there for exactly this.

And note `HttpClient.Timeout` starts at `Timeout.InfiniteTimeSpan` in the starter. .NET
actually defaults to 100 seconds; it is switched off deliberately so this exercise
matches the languages that really do wait forever — and because a hundred seconds is
Microsoft's opinion about a reasonable wait, not your statement about how long a
checkout may spend pricing a line. The comment in the file says so at length.

## `OrdersService.CheckoutAsync` — read what is NOT there

There is no transaction around it, and that is the most important structural decision in
this service.

Open a connection at the top and commit at the bottom, the way the monolith does, and
you hold a database connection open across two network calls. A slow payments service
then does not merely make checkout slow — it pins one connection per in-flight order
until the pool is empty (ten, here), at which point every other endpoint stops working
too, including the ones that never touch payments. You would have converted a payments
outage into a total outage, through your connection pool.

So: network first, holding nothing; then a short local transaction to write. The cost is
that the charge and the insert are no longer atomic together — if the process dies
between them, a customer is charged for an order that does not exist. That hole is real,
and the honest answers to it (an outbox, a reconciliation job) are the module after this
bootcamp. The monolith closed it with one keyword.

## Regenerating the contract

There is no generated code in this directory, and none in git. One line in
`Orders.csproj` does it:

```xml
<Protobuf Include="$(ProtoDir)/bootcamp/payments/v1/payments.proto"
          ProtoRoot="$(ProtoDir)"
          GrpcServices="Client" />
```

`Grpc.Tools` ships protoc and the C# plugin as prebuilt binaries, runs them during
compilation, and feeds the generated `.cs` straight to the compiler. Nothing lands on
disk that you would ever check in, and **the contract is a build input** — delete a
method from the `.proto` and this project stops compiling.

`GrpcServices="Client"` generates the stub and *not* the service base class. This
process consumes payments; it does not implement it, and generating a server it will
never use is an invitation for somebody to.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | HTTP port |
| `DATABASE_URL` | — | Its own database. Converted from a URI to an Npgsql connection string in `Config` |
| `CATALOG_URL` | `http://catalog:8000` | A service name, resolved by the platform |
| `PAYMENTS_ADDR` | `payments:50051` | Likewise |
| `CATALOG_TIMEOUT_MS` | `1000` | exercise 3.4 |
| `PAYMENTS_TIMEOUT_MS` | `2000` | exercise 3.1 — policy, not a guess |
| `PAYMENTS_RETRY_MAX` | `2` | exercise 3.2 |
| `BREAKER_FAILURE_THRESHOLD` / `BREAKER_RESET_MS` | `5` / `10000` | exercise 3.3 |

Seven variables, five of them about what to do when somebody else fails. Catalog has
two. That ratio is the price of being the service in the middle.
