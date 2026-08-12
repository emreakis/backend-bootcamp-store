// CATALOG — the read side of the store, and the simplest service in the system.
//
// Small enough to read in one file, which is why it is the one to read first.
// Everything here satisfies contracts/catalog.v1.yaml; if this file and that file
// disagree, this file is wrong.
//
// Compare it with monolith/csharp/Catalog/. The SQL is identical. What changed is
// everything around it: its own database, its own process, its own deployment, and a
// Reserve method that no longer exists because stock cannot be taken off a shelf in one
// database inside a transaction that lives in another.

using System.Text.Json;
using Npgsql;

const string Implementation = "csharp";
const string ProblemBase = "https://bootcamp.backendguru.io/problems/";

var port = Environment.GetEnvironmentVariable("PORT") is { Length: > 0 } p ? p : "8000";

// DATABASE_URL arrives as a URI because that is what every platform hands you — compose,
// Heroku, Kubernetes secrets, all of them. Npgsql wants key/value pairs, so the
// translation happens here, once, rather than forcing the deployment to speak .NET's
// dialect. The Java implementation does the same conversion for JDBC.
var url = Environment.GetEnvironmentVariable("DATABASE_URL")
          ?? "postgres://store:store@localhost:5433/catalog";
var uri = new Uri(url);
var credentials = uri.UserInfo.Split(':', 2);
var connectionString = new NpgsqlConnectionStringBuilder
{
    Host = uri.Host,
    Port = uri.Port == -1 ? 5432 : uri.Port,
    Username = Uri.UnescapeDataString(credentials[0]),
    Password = credentials.Length > 1 ? Uri.UnescapeDataString(credentials[1]) : "",
    Database = uri.AbsolutePath.TrimStart('/'),
    MaxPoolSize = 10,
}.ConnectionString;

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls($"http://0.0.0.0:{port}");
builder.Services.ConfigureHttpJsonOptions(options =>
    options.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower);

var app = builder.Build();
var db = NpgsqlDataSource.Create(connectionString);
var logger = app.Services.GetRequiredService<ILogger<Program>>();

// Wait for the database rather than crashing if it is a second behind. compose already
// gates startup on a healthcheck; this is the belt to that braces, because in a real
// platform nothing promises your dependencies start first.
var deadline = DateTime.UtcNow.AddSeconds(30);
while (true)
{
    try
    {
        await using var probe = db.CreateCommand("SELECT 1");
        await probe.ExecuteScalarAsync();
        break;
    }
    catch (NpgsqlException) when (DateTime.UtcNow < deadline)
    {
        logger.LogWarning("waiting for the database");
        await Task.Delay(500);
    }
}

// One error envelope, everywhere — RFC 9457, exactly as contracts/problem.yaml says.
app.Use(async (context, next) =>
{
    try
    {
        await next();
    }
    catch (Exception unexpected)
    {
        // Anything unnamed is a bug. 500, and the detail stays in our logs — never in a
        // response body, where it becomes a client's problem to parse and an attacker's
        // to read.
        logger.LogError(unexpected, "unhandled error on {Path}", context.Request.Path);
        await WriteProblem(context, 500, "internal-error", "Internal server error",
            "The request could not be completed.");
    }
});

// Liveness only — it does not touch the database.
//
// Tempting to run `SELECT 1` here. Don't: if this endpoint failed whenever Postgres
// hiccupped, the platform would start killing catalog pods during a database blip,
// removing capacity exactly when the system is least able to spare it. Liveness answers
// "should I be restarted?", and only this process knows.
app.MapGet("/health", () => Results.Json(new { status = "ok", implementation = Implementation }));

// Keyset pagination. An offset would drift under concurrent inserts; a cursor is a
// position in the data rather than a count of rows someone else can change.
//
// Ask for limit + 1 rows: if the extra one comes back, there is another page.
app.MapGet("/v1/products", async (HttpContext context) =>
{
    var rawLimit = context.Request.Query["limit"].FirstOrDefault();
    var cursor = context.Request.Query["cursor"].FirstOrDefault();

    // The contract declares 1..100 and says an out-of-range value is a 400 in the usual
    // envelope. Binding `int limit` as a minimal-API parameter would let ASP.NET answer
    // `?limit=abc` with its own 400 body — right status, wrong shape. Reading the raw
    // string keeps the framework out of a path the contract already specified.
    var limit = 20;
    if (rawLimit is not null && (!int.TryParse(rawLimit, out limit) || limit is < 1 or > 100))
    {
        await WriteProblem(context, 400, "validation-failed", "Validation failed",
            "limit must be an integer between 1 and 100.");
        return;
    }

    await using var command = string.IsNullOrEmpty(cursor)
        ? db.CreateCommand("SELECT sku, name, price_cents, stock FROM products" +
                           " ORDER BY sku LIMIT $1")
        : db.CreateCommand("SELECT sku, name, price_cents, stock FROM products" +
                           " WHERE sku > $1 ORDER BY sku LIMIT $2");

    if (!string.IsNullOrEmpty(cursor)) command.Parameters.AddWithValue(cursor);
    command.Parameters.AddWithValue(limit + 1);

    var rows = new List<Product>();
    await using (var reader = await command.ExecuteReaderAsync())
    {
        while (await reader.ReadAsync())
        {
            rows.Add(new Product(reader.GetString(0), reader.GetString(1),
                reader.GetInt64(2), reader.GetInt64(3)));
        }
    }

    var hasMore = rows.Count > limit;
    var items = hasMore ? rows.Take(limit).ToList() : rows;
    await context.Response.WriteAsJsonAsync(new ProductPage(items,
        hasMore && items.Count > 0 ? items[^1].Sku : null));
});

// The call `orders` makes during checkout.
//
// Its 404 is the most consequential response in this service. Orders has to turn it into
// a designed order rejection — so it must be unambiguous, carry the sku that was
// missing, and never arrive as a 500. A dependency that fails clearly is a dependency
// you can build on.
app.MapGet("/v1/products/{sku}", async (string sku, HttpContext context) =>
{
    await using var command = db.CreateCommand(
        "SELECT sku, name, price_cents, stock FROM products WHERE sku = $1");
    command.Parameters.AddWithValue(sku);

    await using var reader = await command.ExecuteReaderAsync();
    if (!await reader.ReadAsync())
    {
        await WriteProblem(context, 404, "product-not-found", "Product not found",
            $"No product with sku '{sku}'.");
        return;
    }

    await context.Response.WriteAsJsonAsync(new Product(
        reader.GetString(0), reader.GetString(1), reader.GetInt64(2), reader.GetInt64(3)));
});

// A path that matches no route. ASP.NET Core's default is an empty 404 body, which is a
// second error shape for clients to learn.
app.MapFallback(async (HttpContext context) =>
    await WriteProblem(context, 404, "product-not-found", "Product not found",
        $"No product with sku '{context.Request.Path}'."));

app.Logger.LogInformation("catalog ({Impl}) listening on :{Port}", Implementation, port);
app.Run();

static async Task WriteProblem(HttpContext context, int status, string kind,
                               string title, string detail)
{
    context.Response.StatusCode = status;
    await context.Response.WriteAsJsonAsync(
        new Problem(ProblemBase + kind, title, status, detail, context.Request.Path),
        new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower },
        contentType: "application/problem+json");
}

// Every property is PascalCase and every field on the wire is snake_case, because of the
// one ConfigureHttpJsonOptions line above.
record Product(string Sku, string Name, long PriceCents, long Stock);

/// <summary>NextCursor is null on the last page — the contract says null, not "".</summary>
record ProductPage(List<Product> Items, string? NextCursor);

record Problem(string Type, string Title, int Status, string Detail, string Instance);
