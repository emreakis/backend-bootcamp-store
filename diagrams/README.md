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
