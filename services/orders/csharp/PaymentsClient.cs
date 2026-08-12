using Grpc.Core;
using Grpc.Net.Client;
using Store.Payments.V1;

namespace Orders;

/// <summary>
/// SOLUTION — exercises 3.1, 3.2 and 3.3.
///
/// <para>Compare with the same file on <c>main</c>:
/// <c>git diff main solution -- services/orders/csharp</c></para>
///
/// <para>Three things arrived, in the order they matter. A deadline, so a slow payments
/// service cannot hold a checkout open forever. A bounded retry, legal only because
/// <c>Charge</c> carries an idempotency key. And a breaker, so that once payments is
/// clearly unwell we stop asking — which fails fast for us and takes load off it.</para>
///
/// <para>The first of those is worth more than the other two together. Delete the retry
/// and the breaker and this service still degrades honestly; delete the deadline and
/// nothing else here can save it.</para>
/// </summary>
public class PaymentsClient : IDisposable
{
    /// <summary>Backoff between attempts. Never zero — an instant retry is just a second failure.</summary>
    private static readonly int[] BackoffMs = [50, 200, 800];

    private readonly GrpcChannel _channel;
    private readonly Payments.PaymentsClient _stub;
    private readonly ILogger<PaymentsClient> _log;
    private readonly CircuitBreaker _breaker;

    public PaymentsClient(ILogger<PaymentsClient> log, ILogger<CircuitBreaker> breakerLog)
    {
        _log = log;
        _channel = GrpcChannel.ForAddress($"http://{Config.PaymentsAddr}");
        _stub = new Payments.PaymentsClient(_channel);
        _breaker = new CircuitBreaker(Config.BreakerFailureThreshold, Config.BreakerResetMs,
            breakerLog);

        _log.LogInformation(
            "payments client -> {Addr} (timeout {Timeout} ms, retries {Retries}, breaker {N}/{Reset} ms)",
            Config.PaymentsAddr, Config.PaymentsTimeoutMs, Config.PaymentsRetryMax,
            Config.BreakerFailureThreshold, Config.BreakerResetMs);
    }

    public async Task<Payment> ChargeAsync(string orderId, long amountCents, string idempotencyKey)
    {
        var request = new ChargeRequest
        {
            OrderId = orderId,
            AmountCents = amountCents,
            Currency = "EUR",
            IdempotencyKey = idempotencyKey,
        };

        // EXERCISE 3.3 — the breaker, checked before anything else.
        //
        // If payments has failed BreakerFailureThreshold times in a row we do not call it
        // at all. That is not pessimism, it is arithmetic: the next call will almost
        // certainly fail too, and it would cost us the full timeout per attempt to find
        // out while adding load to a service that is already struggling.
        if (_breaker.IsOpen())
        {
            _log.LogWarning("order={Order} charge SKIPPED: circuit breaker is open", orderId);
            throw DomainException.PaymentsUnavailable(
                "The payment service is not answering, so we stopped calling it. " +
                "No charge was made.");
        }

        StatusCode? lastCode = null;

        // EXERCISE 3.2 — a BOUNDED retry.
        //
        // At most PaymentsRetryMax extra attempts, and only for the two codes that mean
        // "try again": Unavailable (nobody answered) and DeadlineExceeded (somebody
        // answered too slowly). Never for a decline, which is not a failure, and never
        // for InvalidArgument, which is our bug and will be our bug again next time.
        //
        // This is only legal because ChargeRequest carries an idempotency key and
        // payments returns the original response for a key it has seen. Take that away
        // and this loop bills the customer up to three times.
        for (var attempt = 0; attempt <= Config.PaymentsRetryMax; attempt++)
        {
            ChargeResponse response;
            try
            {
                // ========================================================
                // EXERCISE 3.1 — THE DEADLINE. The most important line in this file.
                //
                // UtcNow, not Now: Grpc.Net throws on a non-UTC DateTime, because the
                // deadline goes on the wire as an instant and an instant in an
                // unspecified timezone is not one.
                //
                // Computing it INSIDE the loop is what makes the deadline per attempt,
                // so the worst case is retries + 1 attempts plus backoff: with the
                // defaults, 3 x 2000 ms + 250 ms ~ 6.25 s. State that number out loud,
                // because whoever calls checkout has their own budget.
                //
                // Hoist this line above the loop and all three attempts share one 2 s
                // budget instead — the promise stays at 2 s, but a slow dependency eats
                // the whole thing on attempt one and the retries never happen. Which is
                // the honest lesson underneath: retries fix TRANSIENT failures, not slow
                // ones.
                // ========================================================
                response = await _stub.ChargeAsync(request,
                    deadline: DateTime.UtcNow.AddMilliseconds(Config.PaymentsTimeoutMs));
            }
            catch (RpcException transportFailure)
            {
                var code = transportFailure.StatusCode;

                if (!IsRetryable(transportFailure))
                {
                    // Not retryable, and not the breaker's business either: we sent
                    // something wrong and sending it again will not help.
                    throw new InvalidOperationException(
                        $"payments rejected the request: {code}", transportFailure);
                }

                lastCode = code;
                _breaker.RecordFailure();
                _log.LogWarning("order={Order} charge attempt {N}/{Max} failed: {Code}",
                    orderId, attempt + 1, Config.PaymentsRetryMax + 1, code);

                if (attempt < Config.PaymentsRetryMax)
                {
                    await Task.Delay(BackoffMs[Math.Min(attempt, BackoffMs.Length - 1)]);
                }
                continue;
            }

            _breaker.RecordSuccess();

            // A DECLINE IS NOT A FAILURE. The call succeeded; the answer was "no". It
            // does not count against the breaker and it is never retried.
            if (response.Status == ChargeStatus.Declined)
            {
                _log.LogInformation("order={Order} charge DECLINED: {Reason}",
                    orderId, response.DeclineReason);
                throw DomainException.PaymentDeclined(
                    string.IsNullOrEmpty(response.DeclineReason)
                        ? "The card was declined."
                        : response.DeclineReason);
            }

            _log.LogInformation("order={Order} charge APPROVED auth={Auth} (attempt {N})",
                orderId, response.AuthCode, attempt + 1);
            return new Payment("APPROVED", response.AuthCode);
        }

        // Out of attempts. NO CHARGE WAS MADE — or if one was, the idempotency key means
        // a later retry finds it rather than duplicating it. 503 with Retry-After,
        // because the customer did nothing wrong.
        throw DomainException.PaymentsUnavailable(
            $"The payment service did not respond ({lastCode}) after " +
            $"{Config.PaymentsRetryMax + 1} attempts of {Config.PaymentsTimeoutMs} ms. " +
            "No charge was made.");
    }

    /// <summary>
    /// Which failures are worth trying again — and the one place .NET disagrees with the
    /// other five languages badly enough to change the code you write.
    ///
    /// <para><c>Unavailable</c> (nobody answered) and <c>DeadlineExceeded</c> (somebody
    /// answered too slowly) are the two everybody agrees on. Then there is this, from a
    /// real run of <c>conformance/resilience.py</c> against a slow payments service:</para>
    ///
    /// <code>
    /// Status(StatusCode="Cancelled", Detail="Error starting gRPC call.
    ///   HttpRequestException: The HTTP/2 server reset the stream.
    ///   HTTP/2 error code 'CANCEL' (0x8).")
    /// </code>
    ///
    /// <para>That is OUR OWN DEADLINE, reported under a different name. When it fires,
    /// two things happen at once: Grpc.Net gives up locally, and payments — which is
    /// watching the same deadline, because deadlines propagate — abandons its work and
    /// resets the HTTP/2 stream. Whichever arrives first decides the status. Win the
    /// race and you get <c>DeadlineExceeded</c>; lose it and you get <c>Cancelled</c>
    /// wrapping the peer's RST_STREAM. grpc-java and grpc-go hide that race; Grpc.Net,
    /// sitting on <c>HttpClient</c>, does not.</para>
    ///
    /// <para>It is also why this was FLAKY rather than broken — it passed twice and
    /// failed once before anybody looked at the status code.</para>
    ///
    /// <para>So the check is on the <em>cause</em> and not the code alone. A
    /// <c>Cancelled</c> or <c>Internal</c> whose <c>Status.DebugException</c> is an
    /// <see cref="HttpRequestException"/> never reached the application: the transport
    /// failed, no charge was made, and trying again is exactly right. Retrying either
    /// code unconditionally would not be — a real <c>Cancelled</c> means the caller
    /// deliberately went away, and a real <c>Internal</c> is a server bug that repeating
    /// the request will only repeat.</para>
    /// </summary>
    private static bool IsRetryable(RpcException failure) =>
        failure.StatusCode is StatusCode.Unavailable or StatusCode.DeadlineExceeded
        || (failure.StatusCode is StatusCode.Internal or StatusCode.Cancelled
            && failure.Status.DebugException is HttpRequestException or IOException);

    public void Dispose() => _channel.Dispose();
}

/// <summary>
/// Exercise 3.3 — closed, open, or half-open.
///
/// <para>Half-open is the state people forget, and leaving it out is worse than having
/// no breaker at all: a breaker that never closes again is a permanent outage you built
/// yourself. After <c>resetMs</c> this lets exactly one request through; if it succeeds
/// the breaker closes, and if it fails the clock restarts.</para>
///
/// <para>The lock is not decoration. This client is a singleton serving concurrent
/// requests from the thread pool, so the counter really is shared mutable state — and an
/// unsynchronised one is a bug that only shows up under load, which is the only time
/// this code matters.</para>
/// </summary>
public class CircuitBreaker(int threshold, int resetMs, ILogger<CircuitBreaker> log)
{
    private readonly Lock _gate = new();
    private int _consecutiveFailures;
    private DateTime? _openedAt;

    public bool IsOpen()
    {
        lock (_gate)
        {
            if (_openedAt is null) return false;                          // closed
            if ((DateTime.UtcNow - _openedAt.Value).TotalMilliseconds >= resetMs)
            {
                log.LogInformation("circuit breaker HALF-OPEN: letting one probe through");
                _openedAt = null;                                          // half-open
                return false;
            }
            return true;                                                   // open
        }
    }

    public void RecordSuccess()
    {
        lock (_gate)
        {
            if (_consecutiveFailures > 0)
            {
                log.LogInformation("circuit breaker CLOSED after a success");
            }
            _consecutiveFailures = 0;
            _openedAt = null;
        }
    }

    public void RecordFailure()
    {
        lock (_gate)
        {
            _consecutiveFailures++;
            if (_consecutiveFailures >= threshold && _openedAt is null)
            {
                _openedAt = DateTime.UtcNow;
                log.LogWarning("circuit breaker OPEN after {N} consecutive failures; " +
                    "not calling payments for {Reset} ms", _consecutiveFailures, resetMs);
            }
        }
    }
}
