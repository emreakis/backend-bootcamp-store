// PAYMENTS — a gRPC service, and the only one in the system with no HTTP surface and no
// database.
//
// Nothing outside the store ever calls it, which is why it does not need REST: there is
// no browser to please, no cache to negotiate with, and no human reading its responses.
// What it does need is a contract that cannot drift and a wire format that is cheap on a
// hot path, and that is the case for gRPC in one sentence.

using Microsoft.AspNetCore.Server.Kestrel.Core;
using Payments;

var builder = WebApplication.CreateBuilder(args);

var port = int.TryParse(Environment.GetEnvironmentVariable("PORT"), out var parsed)
    ? parsed : 50051;

builder.WebHost.ConfigureKestrel(options =>
{
    // HTTP/2 with no TLS, explicitly.
    //
    // gRPC requires HTTP/2, and Kestrel will not negotiate up to it over a plaintext
    // connection — there is no ALPN without TLS, so a client and server have to agree
    // out of band. Http2 here is that agreement. Miss this line and every call fails
    // with a protocol error that reads like a networking problem.
    //
    // Plaintext because this hop is inside the cluster; in production a service that
    // moves money gets mTLS.
    options.ListenAnyIP(port, listen => listen.Protocols = HttpProtocols.Http2);
});

builder.Services.AddGrpc();

// The standard gRPC health service. gRPC has its own health-checking protocol rather
// than borrowing HTTP's, so orchestrators probe it the same way in every language.
// Liveness only, same rule as the REST services: it reports on this process, never on
// its dependencies — which is why nothing is registered with AddCheck below.
builder.Services.AddGrpcHealthChecks();
builder.Services.AddHealthChecks();

// Reflection lets grpcurl explore this server with no .proto file in hand:
//     grpcurl -plaintext localhost:50051 list
// Convenient in a classroom, and worth disabling in production.
builder.Services.AddGrpcReflection();

var app = builder.Build();
app.MapGrpcService<PaymentsService>();
app.MapGrpcHealthChecksService();
app.MapGrpcReflectionService();

app.Logger.LogInformation(
    "payments ({Impl}) listening on :{Port}  decline_over={Limit} latency={Latency}ms",
    PaymentsService.Implementation, port, PaymentsService.DeclineOverCents,
    PaymentsService.LatencyMs);

app.Run();
