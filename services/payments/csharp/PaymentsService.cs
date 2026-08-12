using System.Collections.Concurrent;
using System.Security.Cryptography;
using Grpc.Core;
using Store.Payments.V1;

namespace Payments;

/// <summary>
/// Extends the generated base class.
///
/// <para>That is not boilerplate — it is forward compatibility. Add a method to the
/// .proto tomorrow and this still compiles, serving UNIMPLEMENTED for the new one
/// instead of failing to build.</para>
/// </summary>
public class PaymentsService(ILogger<PaymentsService> log)
    : Store.Payments.V1.Payments.PaymentsBase
{
    public const string Implementation = "csharp";

    public static readonly long DeclineOverCents =
        long.TryParse(Environment.GetEnvironmentVariable("PAYMENT_DECLINE_OVER_CENTS"),
            out var limit) ? limit : 500_000;

    public static readonly bool AlwaysDecline =
        Environment.GetEnvironmentVariable("PAYMENT_ALWAYS_DECLINE") == "true";

    // The exercise dial. Set it above the caller's deadline and payments stops being
    // down and starts being SLOW — which is the failure that actually hurts, because a
    // slow service accepts your connection and then holds it.
    public static readonly int LatencyMs =
        int.TryParse(Environment.GetEnvironmentVariable("PAYMENT_LATENCY_MS"),
            out var latency) ? latency : 0;

    /// <summary>
    /// Idempotency, in memory.
    ///
    /// <para>A restart forgets every key, and that is a real limitation left visible
    /// rather than hidden. In production this is a datastore with a TTL, and "where do
    /// idempotency records live, and for how long" is a design question with real
    /// answers. Here it is a dictionary, so you can see the shape of the idea.</para>
    ///
    /// <para>Static because ASP.NET creates a new instance of this class per call, and
    /// concurrent because two retries of the same key really can arrive at once.</para>
    /// </summary>
    private static readonly ConcurrentDictionary<string, ChargeResponse> Charges = new();

    /// <summary>Unary: one request, one reply.</summary>
    public override async Task<ChargeResponse> Charge(ChargeRequest request,
                                                      ServerCallContext context)
    {
        // Idempotency first, before any work. A repeat of a key we have seen returns the
        // ORIGINAL answer and charges nothing — which is the entire reason the caller is
        // allowed to retry this method automatically.
        if (!string.IsNullOrEmpty(request.IdempotencyKey)
            && Charges.TryGetValue(request.IdempotencyKey, out var previous))
        {
            log.LogInformation("charge order={Order} idempotency_key={Key} REPLAYED",
                request.OrderId, request.IdempotencyKey);
            return previous;
        }

        // Injected latency, applied while still watching the caller's deadline. If the
        // caller gave up, so do we — continuing to work for a client that has stopped
        // listening is how an overloaded system stays overloaded.
        //
        // context.CancellationToken is .NET's version of Go's ctx.Done(): gRPC cancels it
        // when the client disconnects or its deadline expires, and passing it to
        // Task.Delay is what turns "wait a while" into "wait a while OR until nobody is
        // listening".
        if (LatencyMs > 0)
        {
            try
            {
                await Task.Delay(LatencyMs, context.CancellationToken);
            }
            catch (OperationCanceledException)
            {
                log.LogInformation("charge order={Order} ABANDONED: context canceled",
                    request.OrderId);
                throw new RpcException(new Status(StatusCode.Cancelled, "the caller gave up"));
            }
        }

        if (request.AmountCents <= 0)
        {
            // A malformed request IS an RPC error, and INVALID_ARGUMENT is the gRPC
            // equivalent of a 400. Contrast with the decline below.
            throw new RpcException(new Status(StatusCode.InvalidArgument,
                $"amount_cents must be positive, got {request.AmountCents}"));
        }

        var declined = AlwaysDecline || request.AmountCents > DeclineOverCents;

        // THE DESIGN DECISION IN THIS FILE.
        //
        // A declined card is not an RPC failure. The call succeeded: we asked the
        // provider, the provider said no, and that answer arrived intact. So this returns
        // OK with status DECLINED, and NOT StatusCode.PermissionDenied.
        //
        // The distinction matters more than it looks. gRPC error codes are how the
        // *transport* reports trouble, and clients quite reasonably retry some of them.
        // Encode a business outcome as one and every retry policy in the system starts
        // re-attempting a decision that will never change — while a genuinely retryable
        // UNAVAILABLE becomes indistinguishable from "this card is stolen".
        //
        // Business outcomes go in the response. Failures go in the status.
        var response = new ChargeResponse { PaymentId = Guid.NewGuid().ToString() };
        if (declined)
        {
            response.Status = ChargeStatus.Declined;
            response.DeclineReason =
                $"amount exceeds the approval limit of {DeclineOverCents} cents";
        }
        else
        {
            response.Status = ChargeStatus.Approved;
            response.AuthCode = $"AUTH-{Convert.ToHexString(RandomNumberGenerator.GetBytes(4))}";
        }

        if (!string.IsNullOrEmpty(request.IdempotencyKey))
        {
            Charges[request.IdempotencyKey] = response;
        }

        log.LogInformation("charge order={Order} amount={Amount} status={Status}",
            request.OrderId, request.AmountCents, response.Status);
        return response;
    }

    /// <summary>
    /// Server streaming, declared in the contract and deliberately not built — see the
    /// note in contracts/proto/bootcamp/payments/v1/payments.proto.
    ///
    /// <para>UNIMPLEMENTED is a defined, catchable answer meaning "this exists in the
    /// contract and not yet in this deployment". That is a far better thing for a
    /// consuming team to receive than a method that hangs or returns an empty stream,
    /// and it is what lets a contract legitimately run ahead of its
    /// implementations.</para>
    /// </summary>
    public override Task WatchStatus(WatchStatusRequest request,
                                     IServerStreamWriter<PaymentStatus> responseStream,
                                     ServerCallContext context)
    {
        throw new RpcException(new Status(StatusCode.Unimplemented,
            "WatchStatus is declared in payments.v1 but not implemented in this deployment"));
    }
}
