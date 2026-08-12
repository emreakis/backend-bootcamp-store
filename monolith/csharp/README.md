# The store — C# (ASP.NET Core minimal APIs)

```bash
dotnet run                                   # from this directory
python tools/smoke.py http://localhost:8080  # from the repo root
```

Or without installing anything but Docker, from the repo root:
`MONOLITH_IMPL=csharp docker compose up --build`

## Files

| File | What it is |
|------|-----------|
| `Config.cs` | Every setting, read from the environment |
| `DomainException.cs` | Domain outcomes — the failures the business decided can happen |
| `Db.cs` | The one connection, and `Transaction<T>` |
| `Catalog/CatalogService.cs` | **MODULE.** Owns `products` |
| `Payments/PaymentsService.cs` | **MODULE.** Owns `payments`. No endpoints of its own |
| `Orders/OrdersService.cs` | **MODULE.** Owns `orders` + `order_lines`. The orchestrator |
| `Program.cs` | The HTTP layer — the only file that knows what a status code is |

## What is idiomatic here

**The whole HTTP layer is one file and it still reads well.** Minimal APIs put the
route, the verb and the handler on one line, and the DI container fills in the services
from the parameter list. Compare `Program.cs` with Spring's controllers — same design,
a third of the ceremony.

**`Db.Command` rewrites `?` into `$p0, $p1, …`.** Microsoft.Data.Sqlite binds parameters
by name, while the other five implementations use positional placeholders. Doing the
translation in one private method keeps every SQL string in the module code
byte-identical across all six languages — the adapter lives at the boundary instead of
leaking into the domain. That is the same instinct Session 2 applies to API contracts.

**One policy handles the naming mismatch.** `JsonNamingPolicy.SnakeCaseLower` turns
`PriceCents` into `price_cents` everywhere, so no record needs a `[JsonPropertyName]`.

**Records with `with`.** `order with { Status = "CANCELLED" }` — the domain objects are
immutable, so a cancelled order is a new value rather than a mutated one. Worth noting
before Session 3, where "who changed this object" becomes "which service changed this
row, and when".
