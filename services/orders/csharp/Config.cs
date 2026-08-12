using Npgsql;

namespace Orders;

/// <summary>
/// Configuration from the environment. Never from code.
///
/// <para>Seven values, five of them about what to do when somebody else fails. Catalog
/// has two. That ratio is the price of being the service in the middle.</para>
///
/// <para>Note what is NOT here: a hostname anybody typed. <c>catalog</c> and
/// <c>payments</c> are service names the platform resolves — compose's DNS today, a
/// Kubernetes Service tomorrow, with no code change. Hard-coding an address is how you
/// make an image that only runs in one place.</para>
/// </summary>
public static class Config
{
    public const string Implementation = "csharp";

    public static string Port => Env("PORT", "8080");

    public static string CatalogUrl => Env("CATALOG_URL", "http://localhost:8000");
    public static string PaymentsAddr => Env("PAYMENTS_ADDR", "localhost:50051");

    // Policy, not guesswork. 2000 ms is a statement about how long a checkout may wait
    // on a charge, made by the people who own checkout — not an estimate of how fast
    // payments happens to be today.
    //
    // All four are read here and then, in this starter, quietly ignored. That is
    // exercise 3.
    public static int CatalogTimeoutMs => EnvInt("CATALOG_TIMEOUT_MS", 1000);
    public static int PaymentsTimeoutMs => EnvInt("PAYMENTS_TIMEOUT_MS", 2000);
    public static int PaymentsRetryMax => EnvInt("PAYMENTS_RETRY_MAX", 2);
    public static int BreakerFailureThreshold => EnvInt("BREAKER_FAILURE_THRESHOLD", 5);
    public static int BreakerResetMs => EnvInt("BREAKER_RESET_MS", 10000);

    /// <summary>
    /// DATABASE_URL arrives as a URI because that is what every platform hands you —
    /// compose, Heroku, Kubernetes secrets, all of them. Npgsql wants key/value pairs,
    /// so the translation happens here, once, rather than forcing the deployment to
    /// speak .NET's dialect.
    ///
    /// <para>The Java implementation does the same conversion for JDBC. Twelve-factor
    /// config is not "read strings from the environment" — it is "accept what the
    /// platform actually gives you".</para>
    /// </summary>
    public static string ConnectionString()
    {
        var url = Env("DATABASE_URL", "postgres://store:store@localhost:5434/orders");
        var uri = new Uri(url);
        var credentials = uri.UserInfo.Split(':', 2);

        return new NpgsqlConnectionStringBuilder
        {
            Host = uri.Host,
            Port = uri.Port == -1 ? 5432 : uri.Port,
            Username = Uri.UnescapeDataString(credentials[0]),
            Password = credentials.Length > 1 ? Uri.UnescapeDataString(credentials[1]) : "",
            Database = uri.AbsolutePath.TrimStart('/'),
            MaxPoolSize = 10,
        }.ConnectionString;
    }

    private static string Env(string key, string fallback) =>
        Environment.GetEnvironmentVariable(key) is { Length: > 0 } value ? value : fallback;

    private static int EnvInt(string key, int fallback) =>
        int.TryParse(Environment.GetEnvironmentVariable(key), out var value) ? value : fallback;
}
