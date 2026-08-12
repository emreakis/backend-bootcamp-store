# payments — C# (Grpc.AspNetCore)

The only service with no HTTP surface and no database.

```bash
cd services && PAYMENTS_IMPL=csharp docker compose up --build payments
```

## The odd one out: this is a *web* project

`Payments.csproj` says `Sdk="Microsoft.NET.Sdk.Web"`, and `Program.cs` builds a
`WebApplication`. That looks wrong for a service with no HTTP surface, and it is not.

.NET serves gRPC **on Kestrel, over HTTP/2**, rather than through a separate server
library. Of the six implementations this is the only one where the gRPC server and the
web server are the same object — which is worth knowing is a .NET choice rather than a
gRPC one. Java, Go, Python, Node and Ruby all start something that is only a gRPC
server.

That choice has one consequence you cannot skip:

```csharp
options.ListenAnyIP(port, listen => listen.Protocols = HttpProtocols.Http2);
```

gRPC requires HTTP/2, and Kestrel will not negotiate up to it over a plaintext
connection — there is no ALPN without TLS, so client and server have to agree out of
band. Miss that line and every call fails with a protocol error that reads like a
networking problem.

## Regenerating the contract

There is no generated code in this directory, and none in git. One line in the `.csproj`
does it:

```xml
<Protobuf Include="$(ProtoDir)/bootcamp/payments/v1/payments.proto"
          ProtoRoot="$(ProtoDir)"
          GrpcServices="Server" />
```

`Grpc.Tools` ships protoc and the C# plugin as prebuilt binaries, runs them during
compilation, and feeds the generated `.cs` straight to the compiler. Nothing lands on
disk that you would ever check in, and the contract is a build input — delete a method
from the `.proto` and this project stops compiling.

`GrpcServices="Server"` generates the abstract base class and **not** a client. This
process implements payments; it does not consume it. Compare with
`services/orders/csharp`, which asks for `"Client"` and gets exactly the other half from
the same file.

## Three decisions worth arguing with

**A declined card returns `OK`.** A decline is a `ChargeResponse` with
`Status = ChargeStatus.Declined`, not `StatusCode.PermissionDenied`.

gRPC status codes are how the *transport* reports trouble, and clients reasonably retry
some of them. Encode a business outcome as one and every retry policy in the system
starts re-attempting a decision that will never change — while a genuinely retryable
`UNAVAILABLE` becomes indistinguishable from "this card is stolen". Business outcomes go
in the response; failures go in the status. A malformed amount really is an RPC error,
and gets `InvalidArgument`.

**Idempotency is checked before any work happens.** A repeat of a seen key returns the
original response and charges nothing. That is the only reason the orders service is
allowed to retry this method automatically.

The dictionary is `static`, and that is not laziness: ASP.NET creates a new instance of
`PaymentsService` per call, so an instance field would forget every key immediately. It
is `ConcurrentDictionary` because two retries of the same key really can arrive at once.
And it is in memory, so a restart forgets everything — a real limitation left visible.

**`WatchStatus` returns `UNIMPLEMENTED` on purpose.** A contract is allowed to run ahead
of its implementations — that is how a consuming team starts building before you have
finished. What is not allowed is running ahead *silently*.

## `context.CancellationToken` is .NET's `ctx.Done()`

`Task.Delay(LatencyMs, context.CancellationToken)` waits on the injected latency **and**
on the caller going away at the same time. gRPC cancels that token when the client
disconnects or its deadline expires, so when an orders service with exercise 3.1 done
times out on this, the log says `ABANDONED: context canceled` immediately rather than
finishing an answer nobody is listening for.

Six languages, six spellings, one idea — and .NET's is the tidiest of them.

## One thing to know about the other side

When *this* server abandons a call, it resets the HTTP/2 stream. A .NET **client**
whose own deadline fired at the same moment may then report `Cancelled` rather than
`DeadlineExceeded`, depending on which arrives first. See the `IsRetryable` note in
`services/orders/csharp/PaymentsClient.cs` on the `solution` branch — it cost a flaky
test to find.

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
