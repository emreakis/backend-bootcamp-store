// ORDERS — the orchestrator.
//
// REST at the edge, gRPC inside, two databases it cannot join across, and the only
// service in this system that can be woken up by somebody else's outage.
//
// Everything here satisfies contracts/orders.v1.yaml; if this file and that file
// disagree, this file is wrong.

using System.Text.Json;
using Orders;

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls($"http://0.0.0.0:{Config.Port}");

// One line, and every property on every record in Model.cs goes out as snake_case.
//
// That is the same convenience the Java implementation gets from one line of
// application.properties, and the same trap: a naming policy configured here and
// depended on there is invisible at the point of use.
builder.Services.ConfigureHttpJsonOptions(options =>
    options.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower);

builder.Services.AddSingleton<OrdersRepository>();
builder.Services.AddSingleton<CatalogClient>();
builder.Services.AddSingleton<PaymentsClient>();
builder.Services.AddSingleton<OrdersService>();

var app = builder.Build();
var logger = app.Services.GetRequiredService<ILogger<Program>>();
await app.Services.GetRequiredService<OrdersRepository>().WaitForDatabaseAsync(logger);

// ---------------------------------------------------------------------------
//  One error envelope, everywhere — RFC 9457, exactly as contracts/problem.yaml says.
//
//  A client that learns this shape once handles every failure this API can produce, and
//  a client written against orders already knows how to read an error from catalog.
//  This middleware is the single place in the process where a domain outcome becomes a
//  status code: the translation happens once, at the edge, not in every service.
// ---------------------------------------------------------------------------
app.Use(async (context, next) =>
{
    try
    {
        await next();
    }
    catch (DomainException designed)
    {
        await WriteProblem(context, designed);
    }
    catch (BadHttpRequestException)
    {
        await WriteProblem(context, DomainException.ValidationFailed(
            "Body must be a JSON object with an `items` array."));
    }
    catch (Exception unexpected)
    {
        // Anything unnamed is a bug. 500, and the detail stays in our logs — never in a
        // response body, where it becomes a client's problem to parse and an attacker's
        // to read.
        logger.LogError(unexpected, "unhandled error on {Path}", context.Request.Path);
        await WriteProblem(context, new DomainException("internal-error",
            "Internal server error", 500, "The request could not be completed."));
    }
});

app.MapPost("/v1/orders", async (CreateOrderRequest body, HttpContext context, OrdersService orders) =>
{
    var idempotencyKey = context.Request.Headers["Idempotency-Key"].FirstOrDefault();
    var order = await orders.CheckoutAsync(body?.Items, idempotencyKey);
    context.Response.Headers.Location = $"/v1/orders/{order.Id}";
    return Results.Json(order, statusCode: 201);
});

app.MapGet("/v1/orders/{id}", async (string id, OrdersService orders) =>
    Results.Json(await orders.GetOrderAsync(id)));

app.MapPost("/v1/orders/{id}/cancel", async (string id, OrdersService orders) =>
    Results.Json(await orders.CancelAsync(id)));

// Liveness only, and here that matters more than anywhere else in the system.
//
// Orders has dependencies, so the temptation to check them is real. Give in to it and a
// payments outage makes orders report unhealthy, and the platform starts restarting
// orders pods — removing capacity from a service that was working, during an incident,
// because we told it to.
//
// Orders is not sick when payments is down. It is degraded. That distinction belongs in
// metrics and alerts, not in the endpoint an orchestrator uses to decide whether to
// kill you.
app.MapGet("/health", () =>
    Results.Json(new { status = "ok", implementation = Config.Implementation }));

// A path that matches no route. ASP.NET Core's default is an empty 404 body, which is a
// second error shape for clients to learn. One envelope, everywhere, including the
// boring cases.
app.MapFallback(async (HttpContext context) =>
    await WriteProblem(context, DomainException.OrderNotFound(context.Request.Path)));

app.Logger.LogInformation("orders ({Impl}) listening on :{Port}",
    Config.Implementation, Config.Port);
app.Run();

static async Task WriteProblem(HttpContext context, DomainException exception)
{
    context.Response.StatusCode = exception.Status;
    context.Response.ContentType = "application/problem+json";
    if (exception.RetryAfterSeconds is { } seconds)
    {
        // Tells a well-behaved client when to come back, so it backs off instead of
        // joining the stampede that is currently keeping the dependency down.
        context.Response.Headers.RetryAfter = seconds.ToString();
    }
    await context.Response.WriteAsJsonAsync(
        Problem.From(exception, context.Request.Path),
        new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower },
        contentType: "application/problem+json");
}
