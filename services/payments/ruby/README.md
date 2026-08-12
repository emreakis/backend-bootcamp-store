# payments — Ruby (grpc gem, no Sinatra)

The only service with no HTTP surface and no database.

```bash
cd services && PAYMENTS_IMPL=ruby docker compose up --build payments
```

## There is no Sinatra here, and that is the first thing to notice

Read the `Gemfile` against `services/catalog/ruby/Gemfile`: no sinatra, no puma, no
rackup, no pg. Two gems, one of which only runs at build time.

That is a fair summary of the difference between the two services. This one has no HTTP
surface, no routes and no database — it is a file that starts a gRPC server.

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
Hence the `$LOAD_PATH.unshift` near the top of `server.rb`.

## Three decisions worth arguing with

**A declined card returns `OK`.** A decline is a `ChargeResponse` with
`status: :CHARGE_STATUS_DECLINED`, not `raise GRPC::PermissionDenied`.

gRPC status codes are how the *transport* reports trouble, and clients reasonably retry
some of them. Encode a business outcome as one and every retry policy in the system
starts re-attempting a decision that will never change — while a genuinely retryable
`UNAVAILABLE` becomes indistinguishable from "this card is stolen". Business outcomes go
in the response; failures go in the status. A malformed amount really is an RPC error,
and gets `INVALID_ARGUMENT`.

**Idempotency is checked before any work happens.** A repeat of a seen key returns the
original response and charges nothing. That is the only reason the orders service is
allowed to retry this method automatically. The `Mutex` is not decoration — the server
runs a thread pool, so two retries of the same key really can arrive at once.

**`watch_status` returns `UNIMPLEMENTED` on purpose.** A contract is allowed to run
ahead of its implementations — that is how a consuming team starts building before you
have finished. What is not allowed is running ahead *silently*.

## A client that set no deadline reports one from 1969

This is the best thing in this directory, and it is a real bug that the conformance
suite caught.

gRPC's C core represents "no deadline" as `gpr_inf_future`, and Ruby's conversion of
that to a `Time` **overflows**. It comes back as `1969-12-31 23:59:59` — one second
before the epoch. So the *absence* of a deadline arrives looking exactly like a deadline
that expired fifty-six years ago:

```
deadline class=Time value=1969-12-31 23:59:59 +0000  delta=-1786521673.5
```

Take that at face value and this server abandons every call from a client that has not
done exercise 3.1 — which is every call, at the start of the session. It would answer
instantly and it would answer `CANCELLED`, so the exercise would look already solved
while being broken in a new way.

Hence the guard in `charge`: **a deadline already in the past when the call starts was
never really set.**

Ruby is also the only one of the six with no cancellation callback at all — no
`ctx.Done()`, no `add_callback`, no `cancelled` event, no `CancellationToken`. It gives
you an absolute `Time` and leaves the arithmetic to you. Same idea, less help from the
library, and one more reason to read `call.deadline` suspiciously.

## Making it fail, on demand

```bash
PAYMENT_LATENCY_MS=30000 docker compose up -d payments   # SLOW
docker compose pause payments                            # BLACK HOLE
docker compose stop payments                             # DOWN
```

See `services/payments/go/README.md` for what each of those actually does to a caller,
and why only the third one is interesting.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `50051` | gRPC port |
| `PAYMENT_DECLINE_OVER_CENTS` | `500000` | ROA-008 costs 529900, so ordering one declines |
| `PAYMENT_ALWAYS_DECLINE` | `false` | Decline everything |
| `PAYMENT_LATENCY_MS` | `0` | The Session 3 dial |
