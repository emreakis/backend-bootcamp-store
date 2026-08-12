using System.Text.Json;

namespace Orders;

/// <summary>
/// The REST half of this service's dependencies.
///
/// <para>In the monolith this was <c>Catalog.GetProduct(db, sku)</c> — a method call
/// that could not fail on its own. It is now an HTTP request over a network, and every
/// one of the eight fallacies applies to it.</para>
/// </summary>
public class CatalogClient
{
    private readonly HttpClient _http;
    private readonly ILogger<CatalogClient> _log;

    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    public CatalogClient(ILogger<CatalogClient> log)
    {
        _log = log;

        // ====================================================================
        // TODO (exercise 3.4) — GIVE THIS CLIENT A TIMEOUT.
        //
        // Read the InfiniteTimeSpan below carefully, because .NET is one of only two
        // languages in this repo that ships a default here at all.
        //
        // HttpClient.Timeout defaults to 100 seconds. It has been switched OFF on
        // purpose, and for two reasons.
        //
        //   1. So this exercise matches the other five languages. Java's RestClient,
        //      Go's bare http.Client and Ruby's Net::HTTP all wait forever out of the
        //      box, and a hundred seconds in a classroom is indistinguishable from
        //      forever anyway.
        //
        //   2. Because a library default is not a policy. A hundred seconds is
        //      Microsoft's opinion about a reasonable wait for an arbitrary HTTP call;
        //      CATALOG_TIMEOUT_MS is *your* statement about how long a checkout may
        //      spend pricing a line. Those are different numbers that happen to share
        //      units, and inheriting one when you meant the other is how a service ends
        //      up with a latency budget nobody chose.
        //
        // So: set it from Config.CatalogTimeoutMs.
        //
        //     Timeout = TimeSpan.FromMilliseconds(Config.CatalogTimeoutMs)
        //
        // Note what HttpClient.Timeout actually covers: the whole operation, connect
        // through last byte of the body, and it surfaces as a TaskCanceledException
        // rather than a TimeoutException. For finer control there is
        // SocketsHttpHandler.ConnectTimeout, and in a real service you probably want
        // both — an unreachable host and a slow body are different problems.
        //
        // Then prove it: `docker compose pause catalog` and post an order. Before the
        // fix the request hangs; after it, you get a 503 in one second. `pause` rather
        // than `stop`, because a stopped container refuses connections instantly and a
        // paused one leaves you hanging — which is the whole point.
        // ====================================================================
        _http = new HttpClient
        {
            BaseAddress = new Uri(Config.CatalogUrl),
            Timeout = Timeout.InfiniteTimeSpan,
        };

        _log.LogInformation("catalog client -> {Url} (timeout {Timeout} ms)",
            Config.CatalogUrl, Config.CatalogTimeoutMs);
    }

    /// <summary>
    /// Price one sku.
    ///
    /// <para>Three outcomes, and all three are designed:</para>
    /// <list type="bullet">
    ///   <item>the product exists — we take its name and price and stop caring about it;</item>
    ///   <item>catalog says 404 — a <em>designed order rejection</em>, not a 500. Passing
    ///         a dependency's status straight through would be lazy; letting it become a
    ///         stack trace would be worse;</item>
    ///   <item>catalog cannot be reached — 503, because the customer did nothing wrong.</item>
    /// </list>
    /// </summary>
    public async Task<ProductSnapshot> FetchAsync(string sku)
    {
        HttpResponseMessage response;
        try
        {
            response = await _http.GetAsync($"/v1/products/{sku}");
        }
        catch (Exception unreachable) when (unreachable is HttpRequestException or TaskCanceledException)
        {
            // Connection refused, DNS failure, or a cancelled request — the last of
            // which is only reachable once exercise 3.4 is done. .NET reports a timeout
            // as a cancellation, which is a genuine trap: catch only HttpRequestException
            // and your timeout handling silently does not run.
            _log.LogWarning("catalog unreachable for sku={Sku}: {Error}", sku, unreachable.Message);
            throw DomainException.CatalogUnavailable(
                "The catalog service could not be reached. No order was placed.");
        }

        if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            throw DomainException.ProductNotFound(sku);
        }
        if (!response.IsSuccessStatusCode)
        {
            _log.LogWarning("catalog answered {Status} for sku={Sku}", (int)response.StatusCode, sku);
            throw DomainException.CatalogUnavailable(
                "The catalog service returned an unusable response. No order was placed.");
        }

        var product = await response.Content.ReadFromJsonAsync<ProductSnapshot>(Json);
        if (product is null)
        {
            throw DomainException.CatalogUnavailable(
                $"Catalog returned an empty body for '{sku}'.");
        }
        return product;
    }
}
