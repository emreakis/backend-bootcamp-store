# The store — Go (stdlib `net/http`)

```bash
go run .                                     # from this directory
python tools/smoke.py http://localhost:8080  # from the repo root
```

Or without installing anything but Docker, from the repo root:
`MONOLITH_IMPL=go docker compose up --build`

## Files

| File | What it is |
|------|-----------|
| `internal/config` | Every setting, read from the environment |
| `internal/errs` | Domain outcomes — the failures the business decided can happen |
| `internal/storedb` | The one connection, `Querier`, and `InTx` |
| `internal/catalog` | **MODULE.** Owns `products` |
| `internal/payments` | **MODULE.** Owns `payments`. No HTTP surface of its own |
| `internal/orders` | **MODULE.** Owns `orders` + `order_lines`. The orchestrator |
| `main.go` | The HTTP layer — the only file that knows what a status code is |

## What is idiomatic here

**One dependency.** `modernc.org/sqlite`, a SQLite written in Go, so `CGO_ENABLED=0`
produces a static binary and the runtime image is `alpine` plus one file. The UUID
generator in `internal/id` is fifteen lines rather than a third-party module — this repo
is about architecture, not `go.sum`.

**The router is the standard library.** Go 1.22 put the method in the pattern and gave
`ServeMux` path variables, so `GET /v1/products/{sku}` and `r.PathValue("sku")` need no
framework at all.

**`Querier` is the seam.** Both `*sql.DB` and `*sql.Tx` satisfy it, which is why
`catalog.Reserve` can be called standalone or inside somebody else's transaction without
knowing which. Look at that interface and ask what its equivalent would be if catalog
were across a network — there isn't one, and that absence is Session 3.

**Package boundaries are compiler-enforced.** Everything unexported in
`internal/catalog` is unreachable from `internal/orders`. Go gives you the strongest
version of the module rule of the six — though even it cannot stop you writing
`SELECT * FROM products` in the wrong package.
