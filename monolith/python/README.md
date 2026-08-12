# The store — Python (FastAPI)

```bash
uv run uvicorn app.main:app --port 8080     # from this directory
python tools/smoke.py http://localhost:8080 # from the repo root
```

Or without installing anything but Docker, from the repo root:
`MONOLITH_IMPL=python docker compose up --build`

## Files

| File | What it is |
|------|-----------|
| `app/config.py` | Every setting, read from the environment |
| `app/errors.py` | Domain outcomes — the failures the business decided can happen |
| `app/db.py` | The one connection, and `transaction()` |
| `app/catalog.py` | **MODULE.** Owns `products` |
| `app/payments.py` | **MODULE.** Owns `payments`. No HTTP surface of its own |
| `app/orders.py` | **MODULE.** Owns `orders` + `order_lines`. The orchestrator |
| `app/main.py` | The HTTP layer — the only file that knows what a status code is |

## What is idiomatic here

**The connection is passed explicitly.** `catalog.reserve(conn, sku, qty)` — you can
watch the transaction being handed from module to module. Java, C#, TypeScript and Ruby
all use an ambient transaction instead, which reads more cleanly and hides the
assumption much better. When catalog becomes a service in Session 3, this parameter is
the first thing to go, and Python is where that is most visible.

**Pydantic models are the contract.** One declaration in `main.py` does request
validation, response serialisation and the OpenAPI document. Start the server and open
<http://localhost:8080/docs> — you already have a machine-readable contract nobody
wrote. Session 2 is about writing one on purpose, and about what that free one gets
wrong.

**Endpoints are `def`, not `async def`.** `sqlite3` is synchronous, so FastAPI runs
these in a threadpool. Making them `async` would block the event loop on every query —
a real and common bug, left visible here rather than papered over.
