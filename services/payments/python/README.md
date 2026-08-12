# payments — Python (grpcio)

The only service with no HTTP surface and no database.

```bash
cd services && PAYMENTS_IMPL=python docker compose up --build payments
```

## Regenerating the contract

There is no generated code in this directory, and none in git. The Dockerfile runs this
before it copies a single line of our source:

```bash
python -m grpc_tools.protoc -I contracts/proto \
  --python_out=. --pyi_out=. --grpc_python_out=. \
  bootcamp/payments/v1/payments.proto
```

That ordering is the point. `server.py` inherits from a base class it does not define,
and if you delete a method from the `.proto` this service stops implementing it. A
contract you can break the build with is a different kind of object from a contract you
can only read.

The generated package lands at `bootcamp/payments/v1/` because that is the path the
`.proto` was found at relative to `-I`. protoc derives module names from paths, so the
directory layout in `contracts/proto` *is* the namespace — which is why the file lives
three directories deep instead of being called `payments.v1.proto`.

## Three decisions worth arguing with

**A declined card returns `OK`.** Look at `Charge`: a decline is a `ChargeResponse` with
`status = DECLINED`, not `context.abort(PERMISSION_DENIED, …)`.

gRPC status codes are how the *transport* reports trouble, and clients reasonably retry
some of them. Encode a business outcome as one and every retry policy in the system
starts re-attempting a decision that will never change — while a genuinely retryable
`UNAVAILABLE` becomes indistinguishable from "this card is stolen". Business outcomes go
in the response; failures go in the status. A malformed amount, by contrast, really is
an RPC error, and gets `INVALID_ARGUMENT`.

**Idempotency is checked before any work happens.** A repeat of a seen key returns the
original response and charges nothing. That is the only reason the orders service is
allowed to retry this method automatically — add retries to a call without this and you
have not added resilience, you have added a double-billing bug that appears under load.

The dict is in memory, so a restart forgets every key. That is a real limitation left
visible: in production this is a datastore with a TTL, and "where do idempotency records
live, and for how long" is a design question with real answers.

**`WatchStatus` returns `UNIMPLEMENTED` on purpose.** It is in the contract because a
contract is allowed to run ahead of its implementations — that is how a consuming team
starts building before you have finished. What is not allowed is running ahead
*silently*; `UNIMPLEMENTED` is a defined, catchable answer meaning "this exists in the
contract and not yet in this deployment".

## Two Python-specific things

**`ThreadPoolExecutor(max_workers=10)` is a capacity decision, not a default.** Python's
gRPC server is thread-per-request: every in-flight `Charge` holds one, so an eleventh
concurrent slow call waits. Set `PAYMENT_LATENCY_MS` high and this server runs out of
workers long before it runs out of anything else — a bounded pool being exactly the sort
of resource a caller *without a deadline* exhausts on your behalf.

**`context.add_callback` is how Python spells `select { case <-ctx.Done(): }`.** It fires
when the RPC terminates for any reason, deadline included, so waiting on that `Event` is
what lets `Charge` abandon its injected latency the moment the caller stops listening.
Watch the log say `ABANDONED: context canceled` when an orders service with exercise 3.1
done times out on it. Deadline propagation is a gRPC feature you get for free, and it is
why continuing to work for a client that stopped listening — the thing that keeps an
overloaded system overloaded — does not happen here.

## Making it fail, on demand

```bash
PAYMENT_LATENCY_MS=30000 docker compose up -d payments   # SLOW
docker compose pause payments                            # BLACK HOLE
docker compose stop payments                             # DOWN
```

See `services/payments/go/README.md` for what each of those actually does to a caller,
and why only the third one is interesting.

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
same way in every language. Liveness only, same rule as the REST services: it reports on
this process, never on its dependencies.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `50051` | gRPC port |
| `PAYMENT_DECLINE_OVER_CENTS` | `500000` | ROA-008 costs 529900, so ordering one declines |
| `PAYMENT_ALWAYS_DECLINE` | `false` | Decline everything |
| `PAYMENT_LATENCY_MS` | `0` | The Session 3 dial. Raise it above the orders timeout and payments stops being down and starts being slow |
