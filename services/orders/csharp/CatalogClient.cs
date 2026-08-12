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
        // EXERCISE 3.4 — the timeout.
        //
        // Two of them, and the split is the useful part. SocketsHttpHandler.ConnectTimeout
        // is "I cannot reach this host"; HttpClient.Timeout covers the whole operation,
        // connect through last byte of the body. Different failures with different
        // causes, and only the second is what `docker compose pause catalog` produces.
        //
        // Both come from the same environment variable here because one number is enough
        // for a teaching system. In a real service they differ: connect is fast and
        // unforgiving, the overall budget is generous enough for the slowest legitimate
        // response.
        //
        // Note what this replaced: Timeout.InfiniteTimeSpan, not .NET's 100-second
        // default. That default was switched off on `main` on purpose, because a hundred
        // seconds is Microsoft's opinion about a reasonable wait and CATALOG_TIMEOUT_MS
        // is *your* statement about how long a checkout may spend pricing a line.
        //
        // And note the catch clause in FetchAsync: .NET reports a timeout as
        // TaskCanceledException, not TimeoutException. Catch only HttpRequestException
        // and this whole change silently does nothing but turn a hang into a 500.
        //
        // Prove it: `docker compose pause catalog` and post an order. Before this change
        // the request hung; now it is a 503 in one second.
        // ====================================================================
        var handler = new SocketsHttpHandler
        {
            ConnectTimeout = TimeSpan.FromMilliseconds(Config.CatalogTimeoutMs),
        };

        _http = new HttpClient(handler)
        {
            BaseAddress = new Uri(Config.CatalogUrl),
            Timeout = TimeSpan.FromMilliseconds(Config.CatalogTimeoutMs),
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
