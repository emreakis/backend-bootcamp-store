# The store, six times

The same program in six languages. Same endpoints, same status codes, same JSON, same
seed data, same port. [`API.md`](API.md) is the specification all six satisfy, and
`tools/smoke.py` is the arbiter — 66 checks, and every implementation here passes all
of them.

## Running one

With Docker and nothing else installed, from the repo root:

```bash
MONOLITH_IMPL=go docker compose up --build
```

Natively, from inside the language's folder:

| Language | Prerequisite | Command |
|----------|--------------|---------|
| [python](python) | Python 3.11+, [uv](https://docs.astral.sh/uv/) | `uv run uvicorn app.main:app --port 8080` |
| [java](java) | JDK 21+, Maven | `mvn spring-boot:run` |
| [typescript](typescript) | Node 22.5+ | `npm install && npm start` |
| [csharp](csharp) | .NET 10 SDK | `dotnet run` |
| [go](go) | Go 1.22+ | `go run .` |
| [ruby](ruby) | Ruby 3.2+, a C compiler | `bundle install && bundle exec ruby app.rb` |

Native runs read `db/schema.sql` and `db/seed.sql` through the default relative paths,
so start them from their own directory. Everything else is defaulted; see the
configuration table in [`API.md`](API.md) to change any of it.

## Reading them

Open two side by side. The similarity is the argument Session 2 is built on: the design
transfers, and only the syntax changes.

Each implementation has the same six pieces, whatever they are called:

| Piece | What it does |
|-------|--------------|
| config | Every setting, read from the environment, never from code |
| errors | The domain outcomes — the failures the business decided can happen |
| database | The one connection, and the transaction that spans all three modules |
| catalog | MODULE. Owns `products`. Prices and stock |
| payments | MODULE. Owns `payments`. Charges the card. No HTTP surface of its own |
| orders | MODULE. Owns `orders` + `order_lines`. The orchestrator, and the only module that depends on the other two |
| http layer | The only place in the process that knows what a status code is |

## The one thing to read

`checkout`, in the orders module of whichever language you picked. Three numbered
steps: reserve stock, write the order, charge the card. It is the same three steps
Session 3 spreads across three services and two protocols.

The difference is not the steps. It is that here they either all happen or none of them
do, and there is no state in between that anyone can observe.

## Where the interesting differences are

The six are deliberately close, but each does one thing in its own idiom, and those are
the spots worth comparing:

- **Python and Go pass the connection explicitly.** `catalog.reserve(conn, sku, qty)` —
  you can see the transaction being handed around. When catalog becomes a service, that
  parameter is the first casualty.
- **Java, C#, TypeScript and Ruby use an ambient transaction.** Nothing in
  `catalog.reserve` mentions one; it joins whatever the caller opened, because they
  share a connection. Cleaner to read, and a much better hiding place for the
  assumption that the two writes are atomic.
- **Java and C# have RFC 9457 in the framework.** Spring's `ProblemDetail` and ASP.NET's
  problem support mean the error envelope is not something this project invented. The
  other four build it by hand — compare `problem.filter.ts` with `ProblemAdvice.java`.
- **C# rewrites `?` placeholders** into named parameters in `Db.cs`, so the SQL strings
  in the module code stay byte-identical to the other five.
