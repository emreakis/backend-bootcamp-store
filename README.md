# The Store — Bootcamp

[![contract](https://github.com/emreakis/backend-bootcamp-store/actions/workflows/contract.yml/badge.svg)](https://github.com/emreakis/backend-bootcamp-store/actions/workflows/contract.yml)

The running example for the three-session Bootcamp. One small online store,
built the same way six times, then pulled apart into services.

> **Session 1 — Distributed architectures.** Today you get the *before* picture: the
> store as a **modular monolith**. One process, one database, one deployment, three
> modules. Read it, then argue about where you would cut it.
>
> **Session 2 — API design.** The cuts become **contracts** — REST for the edge,
> gRPC for the internal hop.
>
> **Session 3 — Building microservices.** The contracts become **three running
> services**. Then we break them on purpose and fix them properly.

---

## Pick your language

The store is implemented six times. Every implementation exposes **byte-for-byte the
same HTTP API on the same port with the same seed data**, so you can follow the whole
bootcamp in the language you actually work in.

| Language   | Framework            | Storage driver          | Where |
|------------|----------------------|-------------------------|-------|
| Python     | FastAPI              | stdlib `sqlite3`        | [`monolith/python`](monolith/python) |
| Java       | Spring Boot          | `sqlite-jdbc`           | [`monolith/java`](monolith/java) |
| TypeScript | NestJS               | built-in `node:sqlite`  | [`monolith/typescript`](monolith/typescript) |
| C#         | ASP.NET Core minimal | `Microsoft.Data.Sqlite` | [`monolith/csharp`](monolith/csharp) |
| Go         | stdlib `net/http`    | `modernc.org/sqlite`    | [`monolith/go`](monolith/go) |
| Ruby       | Sinatra              | `sqlite3`               | [`monolith/ruby`](monolith/ruby) |

They are deliberately close to line-for-line. Open two of them side by side — that
similarity is the point, and it is the argument Session 2 is built on: **the design
transfers, only the syntax changes.**

## Run it

With Docker, nothing else installed:

```bash
MONOLITH_IMPL=python docker compose up --build     # or java | typescript | csharp | go | ruby
```

Windows PowerShell:

```powershell
$env:MONOLITH_IMPL = "python"; docker compose up --build
```

Then, in another terminal:

```bash
curl localhost:8080/health
curl localhost:8080/v1/products
curl -X POST localhost:8080/v1/orders \
     -H 'content-type: application/json' \
     -d '{"items":[{"sku":"GRD-002","qty":1},{"sku":"BNS-005","qty":2}]}'
```

To run natively instead — `uv run`, `mvn spring-boot:run`, `npm start`, `dotnet run`,
`go run .`, `bundle exec ruby app.rb` — see the README inside each language folder.

Verify any implementation against the shared contract (66 checks, needs only Python 3.11+
and no packages):

```bash
python tools/smoke.py http://localhost:8080
```

That script is language-neutral on purpose — it speaks HTTP and has no idea which of
the six it is talking to. It is the seed of the conformance suite we use in Session 3,
and it is how you check your own implementation if your language is not one of the six.

The badge at the top is that same script, run against all six on every push. "These six
behave identically" is a claim, and a claim nobody re-checks is a claim that quietly
stops being true.

## What makes it *modular*

Three modules — `catalog`, `orders`, `payments` — inside one deployable:

```
            ┌──────────────────── one process, one deployment ────────────────────┐
            │                                                                     │
  HTTP ───► │   orders ──in-process call──► catalog        (price and stock)      │
            │      │                                                              │
            │      └────in-process call──► payments        (charge the card)      │
            │                                                                     │
            └───────────────────────── one SQLite database ────────────────────────┘
```

One rule, and the whole bootcamp depends on it:

> **A module reads and writes only the tables it owns. Everything else goes through
> another module's public API.**

`db/schema.sql` marks every table with its owner. How much of that rule your tools can
actually enforce varies, and comparing the six is instructive:

- **Go, Java, C#** enforce the *public API* half at compile time — unexported functions,
  package-private classes and `private` members are unreachable from another module, so
  the only way in is the surface each module chose to publish.
- **TypeScript** enforces it at wiring time: Nest refuses to inject a provider whose
  module did not `export` it. Delete one line from `catalog.module.ts` and `orders`
  stops working.
- **Ruby** enforces almost none of it, which makes it the most honest of the six — the
  boundary holds only because someone wrote it down and the team kept to it.

No language enforces the *other* half: that the string `products` appears in exactly one
module. That is discipline, everywhere, and it is why monoliths rot.

## What the monolith gets for free

These are not nostalgia. They are the bill Session 3 pays:

1. **One transaction.** Checkout reserves stock, writes the order and charges the
   card inside a single ACID transaction. Payment declined? Everything rolls back,
   including the stock. Order one `ROA-008` (priced above the decline threshold) and
   watch it happen — the stock is exactly where it was.
2. **Foreign keys across the whole domain.** `order_lines.sku` really does reference
   `products.sku`. The database will not let you sell a product that does not exist.
3. **Calls that cannot fail.** `orders` calling `catalog` is a function call. It has
   no timeout, no retry, no circuit breaker, and no partial failure, because a module
   cannot be down while its caller is up.

On Saturday, all three go away. Sessions 2 and 3 are about what you build to replace them.

## The same store, as three services

Sessions 2 and 3 take the picture above apart. Same store, same data, same behaviour —
now three processes, two databases, two protocols, and every combination of the six
languages:

```bash
cd services
docker compose up --build                                        # the defaults
CATALOG_IMPL=go ORDERS_IMPL=csharp PAYMENTS_IMPL=ruby docker compose up --build
```

**Eighteen implementations, 216 combinations, one set of contracts.** That is the
"smart endpoints, dumb pipes" argument in a command line: a container is an interface,
and behind it the language is nobody's business.

| | Protocol | Languages |
|---|---|---|
| [`services/catalog`](services/catalog) | REST, read-only | all six |
| [`services/orders`](services/orders) | REST in, gRPC out — the orchestrator, and where the exercise lives | all six |
| [`services/payments`](services/payments) | gRPC only, no HTTP, no database | all six |

Check any combination:

```bash
python conformance/contract.py                    # 87 checks, HTTP only, stdlib only
python conformance/resilience.py                  # the exercise, before
python conformance/resilience.py --expect-fixed   # the exercise, after
```

The `solution` branch fills in the four `TODO (exercise 3.x)` blocks in all six
languages, so `git diff main solution -- services/orders/go` is the answer sheet. See
[SOLUTION.md](https://github.com/emreakis/backend-bootcamp-store/blob/solution/SOLUTION.md).

## Layout

```
db/                 schema.sql + seed.sql — shared by all six monolith implementations
monolith/           the six implementations, plus the API contract they all satisfy
  API.md            the exact contract: endpoints, status codes, error envelope
contracts/          Session 2 — OpenAPI 3.1 for the two REST services, protobuf for the
                    internal hop, and one shared RFC 9457 error envelope
services/           Session 3 — the same store as three services, six languages each
  db/               one schema per service, in separate Postgres containers
  docker-compose.yml
conformance/        contract.py and resilience.py — language-neutral, stdlib only
                    slides.py — the decks, checked against the code they describe
exercises/          the in-session exercises
slides/             the three decks, as presented
diagrams/           their Excalidraw sources — open one, change it, export your own
tools/smoke.py      language-neutral contract check for the monolith
```

## Sessions

| # | Title | Slides | Exercise |
|---|-------|--------|----------|
| 1 | Distributed architectures | [deck](slides/session-1-distributed-architectures.pdf) | [Split this monolith](exercises/session-1-split-the-monolith.md) |
| 2 | API design | [deck](slides/session-2-api-design.pdf) | [Design the contract](exercises/session-2-design-the-contract.md), then diff it against [ours](contracts) |
| 3 | Building microservices | [deck](slides/session-3-building-microservices.pdf) | [Break it, then fix it properly](exercises/session-3-break-it-and-fix-it.md) |

The decks were written before the code was. **Where a slide and this repository disagree,
the repository is right** — see [`slides/README.md`](slides/README.md) for the specifics
and for the script that lists them.

Every session needs Docker, and Session 3 needs it most. Install it before you come and
run the command above **once**, at home, on a connection you trust — a first `docker
pull` shared with thirty other people should not cost you an exercise.

---

Emre Akış · [Software Design and Architecture Bootcamp](https://www.backendguru.com/products/software-design-and-architecture-bootcamp) · [backendguru.com](https://www.backendguru.com/)
