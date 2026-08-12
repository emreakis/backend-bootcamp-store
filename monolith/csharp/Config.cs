namespace Store;

/// <summary>
/// Configuration comes from the environment. Never from code.
///
/// Twelve-factor, and the reason it matters here: the artifact you run in Session 3
/// is identical in dev and prod. Only the environment around it changes. Hard-code
/// one address and that stops being true.
/// </summary>
public static class Config
{
    public const string Implementation = "csharp";

    public static string Port { get; } = Str("PORT", "8080");
    public static string DatabasePath { get; } = Str("DATABASE_PATH", "./store.db");
    public static string SchemaPath { get; } = Str("SCHEMA_PATH", "../../db/schema.sql");
    public static string SeedPath { get; } = Str("SEED_PATH", "../../db/seed.sql");
    public static bool ResetDb { get; } = Str("RESET_DB", "true") != "false";

    // The payment stub is deterministic on purpose. A demo that fails randomly
    // teaches nothing; a demo that fails on command teaches one thing at a time.
    public static long PaymentDeclineOverCents { get; } = Num("PAYMENT_DECLINE_OVER_CENTS", 500_000);
    public static bool PaymentAlwaysDecline { get; } = Str("PAYMENT_ALWAYS_DECLINE", "false") == "true";

    private static string Str(string key, string fallback) =>
        Environment.GetEnvironmentVariable(key) is { Length: > 0 } value ? value : fallback;

    private static long Num(string key, long fallback) =>
        long.TryParse(Environment.GetEnvironmentVariable(key), out var parsed) ? parsed : fallback;
}
