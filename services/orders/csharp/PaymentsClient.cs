using Grpc.Core;
using Grpc.Net.Client;
using Store.Payments.V1;

namespace Orders;

/// <summary>
/// THE FILE THE SESSION 3 EXERCISE LIVES IN.
///
/// <para>The gRPC half of this service's dependencies, and the one that will take the
/// store down with it if you let it. Everything inside <c>ChargeAsync</c> is the shape
/// of a remote call that has not yet been made safe.</para>
///
/// <para>Try it. All three of these break payments, and they do not break it the same
/// way:</para>
/// <code>
///   PAYMENT_LATENCY_MS=30000 docker compose up -d payments   # SLOW
///   docker compose pause payments                            # BLACK HOLE
///   docker compose stop payments                             # DOWN
/// </code>
///
/// <para>The first two hang, in every language, every time. A slow server accepts your
/// connection and then never answers; a <em>paused</em> one keeps its address and takes
/// your SYN packets without acknowledging them, which is what a crashed host or a
/// network partition looks like from the outside.</para>
///
/// <para>The third is the one that surprises people, because it is not one behaviour. A
/// stopped container loses its address and its DNS entry, and how long the failure
/// takes is decided by whichever gRPC library you happen to be using. Measured on this
/// stack, with no deadline anywhere: this one — C#, on HttpClient — gives up in about
/// 4 seconds; Python, Go and Ruby take about 20 (their own connect timeout); Java and
/// TypeScript were still waiting after 25.</para>
///
/// <para>Same outage, same contract, four seconds to never. <b>That</b> is the argument
/// for the deadline: without one, how long checkout hangs is a property of somebody
/// else's default rather than a number you chose — and 20 seconds is not "fast" for a
/// checkout, it is a hang with extra steps.</para>
///
/// <para>Meanwhile <c>GET /health</c> on this service keeps answering 200, because
/// orders is not sick. Its dependency is. Watching a completely healthy service become
/// unusable anyway is the moment Session 3 exists for, and it is the fallacy from
/// Session 1 — <em>the network is reliable</em> — collecting its debt.</para>
///
/// <para>There is no generated code in this directory and none in git. Grpc.Tools runs
/// protoc during the build, so <c>Store.Payments.V1</c> above is the contract,
/// compiled. Delete a field from the .proto and this file stops compiling.</para>
/// </summary>
public class PaymentsClient : IDisposable
{
    private readonly GrpcChannel _channel;
    private readonly Payments.PaymentsClient _stub;
    private readonly ILogger<PaymentsClient> _log;

    public PaymentsClient(ILogger<PaymentsClient> log)
    {
        _log = log;

        // The channel is built once and reused for the life of the process.
        //
        // It is not a connection. It is a managed thing that resolves the name, opens
        // connections as needed, multiplexes concurrent calls over HTTP/2 and
        // reconnects on its own after a failure. Building one per request is both slow
        // and a misunderstanding of what it is.
        //
        // `http://` rather than `https://` because this hop is inside the cluster; in
        // production a service that moves money gets mTLS. `payments` is not a hostname
        // anybody configured — it is a service name the platform resolves.
        _channel = GrpcChannel.ForAddress($"http://{Config.PaymentsAddr}");
        _stub = new Payments.PaymentsClient(_channel);

        _log.LogInformation("payments client -> {Addr} (timeout {Timeout} ms, retries {Retries})",
            Config.PaymentsAddr, Config.PaymentsTimeoutMs, Config.PaymentsRetryMax);
    }

    /// <summary>
    /// Charge the card.
    /// </summary>
    /// <param name="idempotencyKey">
    /// The order id, which makes this call safe to repeat — and is therefore the
    /// precondition for exercise 3.2. Retrying a charge without one bills the customer
    /// twice.
    /// </param>
    public async Task<Payment> ChargeAsync(string orderId, long amountCents, string idempotencyKey)
    {
        var request = new ChargeRequest
        {
            OrderId = orderId,
            AmountCents = amountCents,
            Currency = "EUR",
            IdempotencyKey = idempotencyKey,
        };

        ChargeResponse response;
        try
        {
            // ================================================================
            // TODO (exercise 3.1) — GIVE THIS CALL A DEADLINE.       [do this first]
            //
            // `ChargeAsync(request)` waits forever. Not "a long time" — forever. The
            // default value of a missing deadline is the worst value it could have, and
            // it is the single most important line missing from this file.
            //
            // Every generated method takes one, as an optional argument:
            //
            //     await _stub.ChargeAsync(request,
            //         deadline: DateTime.UtcNow.AddMilliseconds(Config.PaymentsTimeoutMs));
            //
            // UtcNow, not Now. Grpc.Net throws if you hand it a non-UTC DateTime, which
            // is the library refusing to guess — the deadline goes on the wire as an
            // instant, and an instant in an unspecified timezone is not one.
            //
            // Note it is per CALL, not per client. There is no way to set it once on the
            // stub and forget it, and that is deliberate across every gRPC library: a
            // deadline is a property of the request you are making right now, not of the
            // connection you happen to be making it over.
            //
            // The deadline also travels: payments sees the caller's remaining budget and
            // abandons its own work when the budget runs out, instead of finishing an
            // answer nobody is listening for. Watch the payments log say
            // "ABANDONED: context canceled" the moment this expires.
            //
            // Verify: PAYMENT_LATENCY_MS=30000, then POST an order. Before, it hangs;
            // after, you get a 503 in two seconds.
            // ================================================================

            // ================================================================
            // TODO (exercise 3.2) — RETRY, BUT ONLY BECAUSE YOU MAY.       [then this]
            //
            // Wrap the call in a bounded retry: at most Config.PaymentsRetryMax extra
            // attempts, with backoff between them (say 50 ms, then 200 ms), and ONLY for
            // StatusCode.Unavailable and StatusCode.DeadlineExceeded.
            //
            // Three rules, each of which someone learns the hard way:
            //
            //   1. Only retry what is safe to repeat. This call is, because
            //      ChargeRequest carries an idempotency key and payments returns the
            //      original response for a key it has seen. Delete that field and this
            //      exercise becomes a double-billing bug.
            //
            //   2. Never retry a business outcome. A declined card will be declined
            //      again; retrying it just costs the customer time.
            //
            //   3. Bound it, and back off. Retrying into an overloaded service is how a
            //      brownout becomes an outage — you add load to the exact system that is
            //      failing from load. Three attempts and a budget, not "retry until
            //      success".
            //
            // Grpc.Net.Client also ships a declarative retry policy on the channel
            // (GrpcChannelOptions.ServiceConfig), and Polly does this properly for
            // anything. Write the loop by hand once first, because then you know what
            // they are doing.
            // ================================================================

            // ================================================================
            // TODO (exercise 3.3) — PUT A CIRCUIT BREAKER IN FRONT.        [last]
            //
            // Count consecutive failures. At Config.BreakerFailureThreshold, stop
            // calling payments at all and fail immediately for Config.BreakerResetMs;
            // then let one probe through and close on success.
            //
            // A breaker does two jobs, and the second is the one people forget:
            //
            //   * it turns a slow hang into an instant, designed failure, so orders
            //     stops burning thread-pool threads on a call it can predict will fail;
            //     and
            //   * it takes load OFF payments, giving it room to recover. Without one, a
            //     struggling service is held under by the traffic of everyone politely
            //     waiting for it.
            //
            // This client is a singleton serving concurrent requests, so your counter is
            // shared mutable state. Interlocked, or a lock, or Polly's
            // CircuitBreakerStrategy. Writing the twenty lines yourself once is worth
            // doing first, because then you know what it is doing.
            // ================================================================

            response = await _stub.ChargeAsync(request);
        }
        catch (RpcException transportFailure)
        {
            _log.LogWarning("order={OrderId} charge failed at the transport: {Code}",
                orderId, transportFailure.StatusCode);

            // Transport-level trouble. The customer did nothing wrong, so this is a 5xx
            // and carries Retry-After. Crucially, NO CHARGE WAS MADE — or if one was,
            // the idempotency key means the retry will find it rather than duplicate it.
            if (transportFailure.StatusCode is StatusCode.Unavailable or StatusCode.DeadlineExceeded)
            {
                throw DomainException.PaymentsUnavailable(
                    $"The payment service did not respond within {Config.PaymentsTimeoutMs} ms. " +
                    "No charge was made.");
            }

            // Anything else — InvalidArgument, Unimplemented — means we sent something
            // wrong, which is our bug and not a retry candidate.
            throw new InvalidOperationException(
                $"payments rejected the request: {transportFailure.StatusCode}", transportFailure);
        }

        // A DECLINE IS NOT A FAILURE. The call succeeded; the answer was "no".
        //
        // Payments deliberately returns OK with status DECLINED rather than a gRPC error
        // code, so that no retry policy in the system ever re-attempts a decision that
        // will never change. Here that becomes a 402 — the customer's problem to solve,
        // and not ours.
        if (response.Status == ChargeStatus.Declined)
        {
            _log.LogInformation("order={OrderId} charge DECLINED: {Reason}",
                orderId, response.DeclineReason);
            throw DomainException.PaymentDeclined(
                string.IsNullOrEmpty(response.DeclineReason)
                    ? "The card was declined."
                    : response.DeclineReason);
        }

        _log.LogInformation("order={OrderId} charge APPROVED auth={Auth}", orderId, response.AuthCode);
        return new Payment("APPROVED", response.AuthCode);
    }

    public void Dispose() => _channel.Dispose();
}
