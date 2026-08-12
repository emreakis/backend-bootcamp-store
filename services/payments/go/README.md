# payments — Go (grpc-go)

The only service with no HTTP surface and no database.

```bash
cd services && PAYMENTS_IMPL=go docker compose up --build payments
```

## Regenerating the contract

There is no generated code in this directory, and none in git. The Dockerfile runs
this before it copies a single line of our source:

```bash
protoc -I contracts/proto \
  --go_out=. --go_opt=module=github.com/backendguru/store \
  --go-grpc_out=. --go-grpc_opt=module=github.com/backendguru/store \
  bootcamp/payments/v1/payments.proto
```

That ordering is the point. `main.go` implements an interface it does not define, and
if you delete a method from the `.proto` this build stops compiling. A contract you
can break the build with is a different kind of object from a contract you can only
read.

`go.mod` declares module `github.com/backendguru/store` to match the `go_package`
option in the proto — which is also why the Go *orders* service declares the same
module path. Both sides import the identical generated package, because both were
produced from the identical file.

## Three decisions worth arguing with

**A declined card returns `OK`.** Look at `Charge`: a decline is a `ChargeResponse`
with `status = DECLINED`, not `status.Error(codes.PermissionDenied, …)`.

gRPC status codes are how the *transport* reports trouble, and clients reasonably
retry some of them. Encode a business outcome as one and every retry policy in the
system starts re-attempting a decision that will never change — while a genuinely
retryable `UNAVAILABLE` becomes indistinguishable from "this card is stolen". Business
outcomes go in the response; failures go in the status. A malformed amount, by
contrast, really is an RPC error, and gets `INVALID_ARGUMENT`.

**Idempotency is checked before any work happens.** A repeat of a seen key returns the
original response and charges nothing. That is the only reason the orders service is
allowed to retry this method automatically — add retries to a call without this and
you have not added resilience, you have added a double-billing bug that appears under
load.

The map is in memory, so a restart forgets every key. That is a real limitation left
visible: in production this is a datastore with a TTL, and "where do idempotency
records live, and for how long" is a design question with real answers.

**`WatchStatus` returns `UNIMPLEMENTED` on purpose.** It is in the contract because a
contract is allowed to run ahead of its implementations — that is how a consuming team
starts building before you have finished. What is not allowed is running ahead
*silently*; `UNIMPLEMENTED` is a defined, catchable answer meaning "this exists in the
contract and not yet in this deployment".

## Making it fail, on demand

```bash
docker compose stop payments                     # DOWN: connections refused instantly
docker compose up -d payments                    # back
PAYMENT_LATENCY_MS=30000 docker compose up -d payments   # SLOW: the bad one
```

Slow is worse than down, and it is the failure Session 3 is really about. A service
that is down refuses your connection immediately and you find out at once. A service
that is slow accepts it and holds it, and every caller waits politely until its thread
pool is empty.

`Charge` waits on the injected latency *and* on the caller's context at the same time,
so when the caller's deadline expires the server stops working immediately and logs
`ABANDONED: context canceled`. Deadline propagation is a gRPC feature you get for
free, and it is why continuing to work for a client that stopped listening — the thing
that keeps an overloaded system overloaded — does not happen here.

## Poking it by hand

The server registers gRPC reflection, so `grpcurl` needs no `.proto` in hand:

```bash
grpcurl -plaintext localhost:50051 list
grpcurl -plaintext -d '{"order_id":"o-1","amount_cents":22500,"currency":"EUR","idempotency_key":"k1"}' \
        localhost:50051 bootcamp.payments.v1.Payments/Charge
```

Convenient in a classroom, and worth turning off in production.

It also registers the standard `grpc.health.v1.Health` service — gRPC has its own
health-checking protocol rather than borrowing HTTP's, so orchestrators probe it the
same way in every language. Liveness only, same rule as the REST services: it reports
on this process, never on its dependencies.
