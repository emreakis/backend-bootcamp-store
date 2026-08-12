// The HTTP layer. The only place in the process that knows what a status code is.
//
// Everything the endpoints call is domain logic that would be identical in a console
// app. That separation is not decoration: in Session 3, catalog and payments grow their
// own HTTP and gRPC edges, and the module code underneath them barely changes.

using System.Text.Json;
using System.Text.Json.Serialization;
using Store;
using Store.Catalog;
using Store.Orders;
using Store.Payments;

const string problemBase = "https://bootcamp.backendguru.io/problems/";

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls($"http://0.0.0.0:{Config.Port}");

// The API speaks snake_case; C# speaks PascalCase. One policy reconciles them, so no
// record in this codebase needs a [JsonPropertyName] attribute on every property.
builder.Services.ConfigureHttpJsonOptions(options =>
{
    options.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower;
    options.SerializerOptions.DefaultIgnoreCondition = JsonIgnoreCondition.Never;
});

// One database, shared by every module. That single registration is the architectural
// decision this whole bootcamp interrogates: it is what makes the transaction in
// OrdersService possible, and precisely what Session 3 takes away.
builder.Services.AddSingleton<Db>();
builder.Services.AddSingleton<CatalogService>();
builder.Services.AddSingleton<PaymentsService>();
builder.Services.AddSingleton<OrdersService>();

var app = builder.Build();

// --- errors ------------------------------------------------------------------
//
// One error envelope, everywhere. RFC 9457 Problem Details.
//
// A client that learns this shape once handles every failure this API can produce.
// Bespoke error bodies per endpoint are how you make consumers write a parser per
// endpoint. This middleware is the single place a domain outcome becomes a status code.
app.Use(async (context, next) =>
{
    try
    {
        await next();
    }
    catch (DomainException exception)
    {
        await WriteProblem(context, exception.Status, exception.Kind, exception.Title,
            exception.Detail);
    }
    catch (Exception exception) when (exception is JsonException or BadHttpRequestException)
    {
        // A body the deserialiser could not read is the caller's problem to fix.
        await WriteProblem(context, 400, "validation-failed", "Validation failed",
            "Body must be a JSON object with an `items` array.");
    }
    catch (Exception exception)
    {
        // Anything we did not name is a bug, and the caller must not be told to change
        // its request. 500, and the detail stays in our logs.
        app.Logger.LogError(exception, "unhandled error on {Path}", context.Request.Path);
        await WriteProblem(context, 500, "internal-error", "Internal server error",
            "The request could not be completed.");
    }
});

async Task WriteProblem(HttpContext context, int status, string kind, string title, string detail)
{
    context.Response.StatusCode = status;
    context.Response.ContentType = "application/problem+json";
    await context.Response.WriteAsync(JsonSerializer.Serialize(new
    {
        type = problemBase + kind,
        title,
        status,
        detail,
        instance = context.Request.Path.Value,
    }));
}

// --- endpoints ---------------------------------------------------------------

// Liveness only — deliberately checks nothing downstream.
//
// Session 3 revisits this. A health check that calls its dependencies turns one
// service's outage into everyone's outage, because the platform starts killing healthy
// pods for being downstream of a sick one.
app.MapGet("/health", () => Results.Ok(new
{
    status = "ok",
    implementation = Config.Implementation,
}));

app.MapGet("/v1/products", (CatalogService catalog, string? limit, string? cursor) =>
{
    var parsed = 20;
    if (limit is not null && (!int.TryParse(limit, out parsed) || parsed < 1 || parsed > 100))
    {
        throw DomainException.ValidationFailed("limit must be an integer between 1 and 100.");
    }
    return Results.Ok(catalog.ListProducts(parsed, cursor));
});

app.MapGet("/v1/products/{sku}", (CatalogService catalog, string sku) =>
    Results.Ok(catalog.GetProduct(sku)));

app.MapPost("/v1/orders", (OrdersService orders, CreateOrderRequest? request) =>
{
    var order = orders.Checkout(request?.Items);
    return Results.Created($"/v1/orders/{order.Id}", order);
});

app.MapGet("/v1/orders/{id}", (OrdersService orders, string id) =>
    Results.Ok(orders.GetOrder(id)));

app.MapPost("/v1/orders/{id}/cancel", (OrdersService orders, string id) =>
    Results.Ok(orders.Cancel(id)));

app.Logger.LogInformation("store ({Implementation}) listening on :{Port}",
    Config.Implementation, Config.Port);
app.Run();
