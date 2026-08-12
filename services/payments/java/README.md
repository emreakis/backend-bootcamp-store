# payments — Java (grpc-java, no Spring)

The only service with no HTTP surface and no database.

```bash
cd services && PAYMENTS_IMPL=java docker compose up --build payments
```

## There is no Spring here, and that is the first thing to notice

Read `pom.xml` against `services/orders/java/pom.xml` and
`services/catalog/java/pom.xml`. Those two inherit `spring-boot-starter-parent`; this one
inherits nothing.

This service has no HTTP surface, no controllers, no configuration binding, no
dependency injection and nothing to autowire. It is a `main` that starts a gRPC server
and a class that implements one method. Carrying a framework anyway would be carrying it
for the sake of consistency, which is not a reason — and "every service in this
organisation is a Spring Boot app" is how a 40 MB dependency tree ends up in a process
whose entire job is to say yes or no to a number.

## Regenerating the contract

There is no generated code in this directory, and none in git. The Dockerfile runs
`mvn package`, and the `protobuf-maven-plugin` does this as part of it:

```bash
protoc -I contracts/proto \
  --java_out=target/generated-sources \
  --grpc-java_out=target/generated-sources \
  bootcamp/payments/v1/payments.proto
```

protoc and the grpc-java plugin arrive from Maven Central as prebuilt binaries for the
detected OS and CPU — which is why nothing has to be apt-installed here, unlike the Go
and Node images. That is what the `os-maven-plugin` extension in `<build>` is for.

`compile` produces the messages; `compile-custom` runs the grpc-java plugin and produces
`PaymentsGrpc.PaymentsImplBase`, the class `PaymentsService` extends. Delete a method
from the `.proto` and this stops compiling.

**`protobuf.version` must match what `grpc-protobuf` ships.** Build with protoc 4.31
against gRPC 1.73 — which ships `protobuf-java` 3.25.5 — and you get
`cannot find symbol: method resolveAllFeaturesImmutable()`. Generated code calls into its
runtime, and a newer generator emits calls only a newer runtime has. Check with
`mvn dependency:tree` before changing either number.

## Three decisions worth arguing with

**A declined card returns `OK`.** A decline is a `ChargeResponse` with
`status = DECLINED`, not `Status.PERMISSION_DENIED`.

gRPC status codes are how the *transport* reports trouble, and clients reasonably retry
some of them. Encode a business outcome as one and every retry policy in the system
starts re-attempting a decision that will never change — while a genuinely retryable
`UNAVAILABLE` becomes indistinguishable from "this card is stolen". Business outcomes go
in the response; failures go in the status. A malformed amount really is an RPC error,
and gets `INVALID_ARGUMENT`.

**Idempotency is checked before any work happens.** A repeat of a seen key returns the
original response and charges nothing. That is the only reason the orders service is
allowed to retry this method automatically. The map is a `ConcurrentHashMap` because
gRPC serves every call on a pool thread, so two retries of the same key really can
arrive at once — and it is in memory, so a restart forgets every key. A real limitation
left visible.

**`watchStatus` returns `UNIMPLEMENTED` on purpose.** A contract is allowed to run ahead
of its implementations — that is how a consuming team starts building before you have
finished. What is not allowed is running ahead *silently*.

## `io.grpc.Context` is Java's `ctx`

`Charge` waits on the injected latency **and** on the caller's cancellation at the same
time, via a `CountDownLatch` fed by `Context.current().addListener(...)`. That is the
same idea as Go's `select { case <-time.After(d): case <-ctx.Done(): }`, spelled in
Java. When an orders service with exercise 3.1 done times out on this, the log says
`ABANDONED: context canceled` immediately rather than finishing an answer nobody is
listening for.

Note the `removeListener` in the `finally`. The context outlives the latch, and a
listener left attached to a long-lived context is a leak with a slow fuse.

## The shade plugin needs `ServicesResourceTransformer`

`grpc-netty-shaded` ships `META-INF/services` entries that must be *merged* rather than
overwritten when the fat jar is built. Leave that transformer out and the transport
silently disappears from the jar, and the server fails at startup with a message about
no available transport that tells you nothing about why. Worth knowing before you spend
an evening on it.

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
