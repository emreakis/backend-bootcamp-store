# payments — TypeScript (grpc-js, no NestJS)

The only service with no HTTP surface and no database.

```bash
cd services && PAYMENTS_IMPL=typescript docker compose up --build payments
```

## There is no NestJS here, and that is the first thing to notice

`services/catalog/typescript` and `services/orders/typescript` are Nest applications.
This one is a file that starts a server.

It has no HTTP surface, no controllers, no modules and nothing to inject. Carrying a
framework anyway would be carrying it for the sake of consistency, which is not a
reason. Read `package.json` against the other two: three runtime dependencies, and one
of them is the health service.

## Regenerating the contract

There is no generated code in this repository, and none in git. The Dockerfile runs this
before `tsc` ever sees `src/`:

```bash
protoc -I contracts/proto \
  --plugin=./node_modules/.bin/protoc-gen-ts_proto \
  --ts_proto_out=./src/gen \
  --ts_proto_opt=outputServices=grpc-js,esModuleInterop=true \
  bootcamp/payments/v1/payments.proto
```

ts-proto is a protoc plugin like any other — the same `protoc` that produces Go code for
the payments-go service, pointed at a different back end. It produces the
`ServiceDefinition` that `server.addService` registers, so deleting a method from the
`.proto` stops this build rather than producing a server that silently answers
`UNIMPLEMENTED` for something it used to serve.

**Why not `@grpc/proto-loader`?** Because it reads the `.proto` at *runtime* and hands
you `any`. It works, it is the more common Node habit, and it moves every contract
mismatch from build time to 3am.

One thing this cost: `ts-proto` is a devDependency because it only runs at build time,
but the code it *emits* imports `@bufbuild/protobuf/wire` on every call. That has to be
a runtime dependency, and the image failed to start until it was. Generated code drags
its runtime along.

## Three decisions worth arguing with

**A declined card returns `OK`.** A decline is a `ChargeResponse` with
`status = DECLINED`, not `status.PERMISSION_DENIED`.

gRPC status codes are how the *transport* reports trouble, and clients reasonably retry
some of them. Encode a business outcome as one and every retry policy in the system
starts re-attempting a decision that will never change — while a genuinely retryable
`UNAVAILABLE` becomes indistinguishable from "this card is stolen". Business outcomes go
in the response; failures go in the status.

**Idempotency is checked before any work happens.** A repeat of a seen key returns the
original response and charges nothing. That is the only reason the orders service is
allowed to retry this method automatically.

**`watchStatus` returns `UNIMPLEMENTED` on purpose.** A contract is allowed to run ahead
of its implementations — that is how a consuming team starts building before you have
finished. What is not allowed is running ahead *silently*.

## The `Map` has no lock, and that is the interesting part

Every other implementation of this service guards its idempotency store — a
`ConcurrentHashMap` in Java, a `sync.Mutex` in Go, a `threading.Lock` in Python, a
`ConcurrentDictionary` in C#, a `Mutex` in Ruby. Node needs none of it, because nothing
between the `get` and the `set` can be interleaved.

That is a genuine simplification and it is worth knowing what you pay for it. Node has
no thread pool to exhaust, so the symptom of a hung dependency is not "the pool is full"
— it is memory quietly filling while the process still reports itself healthy. Running
out of threads is at least loud.

## `call.on('cancelled')` is Node's `ctx.Done()`

`charge` waits on the injected latency **and** on the caller going away at the same
time. The `cancelled` event fires for a client cancellation and an expired deadline
alike, so when an orders service with exercise 3.1 done times out on this, the log says
`ABANDONED: context canceled` immediately rather than finishing an answer nobody is
listening for.

Six languages, six spellings, one idea.

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
