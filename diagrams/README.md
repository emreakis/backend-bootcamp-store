# Diagrams

The Excalidraw sources for the diagrams in the decks. Open any of them at
[excalidraw.com](https://excalidraw.com) with **File → Open**, or in the VS Code
extension.

| File | Appears on |
|---|---|
| `01-monolith-anatomy` | Session 1, slide 4 |
| `02-soa-enterprise-service-bus` | Session 1, slide 9 |
| `03-microservices` | Session 1, slide 10 |
| `04-grpc-shared-contract` | Session 2, slide 15 |
| `05-store-architecture-call-flow` | Session 3, slides 5 and 9 |
| `06-failure-in-the-chain` | Session 3, slide 19 |
| `07-failure-diagnosis-fix-frames` | drawn after the decks were exported — on no slide yet |
| `backend-bootcamp-architecture` | a duplicate of `05` |

## Seven more, drawn from the repo

Added 12 August: plain SVG, one per concept the decks teach in text but never drew.
They are generated against this repository, so where a deck and a diagram disagree —
pagination, for instance, lives on `GET /v1/products`, not on orders — the diagram
already agrees with the code.

| File | Supports | The argument it makes |
|---|---|---|
| `08-eight-fallacies` | Session 1, slide 12 | each belief struck out, the design it becomes, and where this repo does it |
| `09-monolith-or-microservices` | Session 1, slide 18 | a decision grid, not a maturity ladder — with the store's own path across it |
| `10-grpc-four-call-shapes` | Session 2, slide 16 | the arrows are the call shapes; the real `payments.proto` lines below |
| `11-cursor-vs-offset-pagination` | Session 2, slide 12 | same catalogue, same insert: offset serves a row twice, the cursor resumes |
| `12-database-per-service` | Session 3, slide 7 | the two `LOST BY SATURDAY` foreign keys, before and after the split |
| `13-order-confirmed-events` | Session 3, slide 13 | who waits and who does not — and that the store ships no broker yet |
| `14-timeouts-retries-breakers` | Session 3, slide 20 | the 6.25 s worst-case budget, drawn to scale, and the breaker's three states |

They render directly on GitHub. For a PNG:

```bash
uv run --with cairosvg python -c "import cairosvg; cairosvg.svg2png(url='diagrams/08-eight-fallacies.svg', write_to='08.png', scale=2)"
```

## Why the sources and not a folder of PNGs

Because these are plain JSON, and a picture you can open is worth more than a picture you
can only look at. Change one, export your own, argue with it.

The call-flow diagram is the one to reach for: Session 1's exercise asks you to decide
where you would cut a monolith you actually work on, and redrawing `05` with your own
service names is the fastest way to find out which of your calls become network calls.

## Two of these are ahead of the decks

`05-store-architecture-call-flow` and `06-failure-in-the-chain` were corrected on
12 August. The PDFs still show the versions from July.

| Was | Now | Why |
|---|---|---|
| `Payments · Java · gRPC · :9090` | `Payments · Go · gRPC · :50051` | the port the service actually listens on, and the implementation `docker compose` brings up by default |
| `1 · POST /orders` | `1 · POST /v1/orders` | the API serves versioned paths |
| `2 · REST GET /products/{sku}` | `2 · REST GET /v1/products/{sku}` | likewise |
| `Charge() — waiting forever` | `Charge() — no deadline` | a stopped payments does **not** wait forever — it fails in about 4 s on C#, 20 s on Python, Go and Ruby, and never on Java and TypeScript. The duration is somebody else's library default; the missing deadline is the actual bug. See `services/README.md` |
