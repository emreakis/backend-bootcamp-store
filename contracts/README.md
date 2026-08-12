# Contracts

The arrows between the boxes. Session 1 argued about where to cut the monolith;
these files are what a cut actually looks like once it has to be written down.

> **Doing the session?** Start with
> [`exercises/session-2-design-the-contract.md`](../exercises/session-2-design-the-contract.md)
> and design the write side before you open `orders.v1.yaml`. Reading the answer first
> is much less useful than disagreeing with it.

| File | Shape | Pins down |
|------|-------|-----------|
| [`catalog.v1.yaml`](catalog.v1.yaml) | OpenAPI 3.1.1 | The REST contract the world reads. Cursor pagination, and why the API is read-only |
| [`orders.v1.yaml`](orders.v1.yaml) | OpenAPI 3.1.1 | Checkout, cancel, idempotency, and the 503 that Session 3 is built around |
| [`proto/…/payments.proto`](proto/bootcamp/payments/v1/payments.proto) | proto3 | The internal contract, where the field **numbers** are the API |
| [`problem.yaml`](problem.yaml) | OpenAPI fragment | One RFC 9457 error envelope, `$ref`'d by both REST contracts |

## Check them

```bash
npx @redocly/cli lint contracts/catalog.v1.yaml contracts/orders.v1.yaml
uv run --with grpcio-tools python -m grpc_tools.protoc -I contracts/proto \
    --python_out=/tmp --grpc_python_out=/tmp bootcamp/payments/v1/payments.proto
```

The proto is named by its **path**, relative to the include root, because that is where
protoc gets the generated module names from. The header comment in the file explains
what a flat `payments.v1.proto` costs you.

Both pass. That sentence is the point of the whole session: "the contract is valid" is
a thing a machine can tell you, and "the prose describes the API accurately" is not.

Read the contracts in a browser instead:

```bash
npx @redocly/cli preview-docs contracts/orders.v1.yaml
```

## Read these three things first

**`orders.v1.yaml` → `POST /v1/orders` → the `Idempotency-Key` header.** A `POST` that
creates something is not safe to retry, and a caller whose network dropped the response
cannot tell a successful charge from a failed one. Everything Session 3 does with
retries depends on this header existing first. Add retries to a call without one and
you have not added resilience — you have added a double-billing bug that only shows up
under load.

**`orders.v1.yaml` → the `503` response.** Most contracts document only the failures
the service causes itself. This one documents what happens when something *else* is
broken, gives it a `Retry-After`, and promises no charge was made. That response is not
free — it is the deliverable of the Session 3 exercise, and without a deadline the real
behaviour is not a 503 but a hang.

**`payments.proto` → the comment block above the messages.** Field *numbers* go on
the wire, not names. Adding a number is safe, renaming is free, and reusing a number
corrupts data silently. `reserved 5;` is how you retire one forever.

## Why the two REST files are so different from the proto

Both describe an API. Only one of them **is** the API.

`catalog.v1.yaml` and `orders.v1.yaml` are documents that six hand-written
implementations promise to satisfy. Nothing stops an implementation drifting from them
except tests somebody remembered to run — which is exactly why `conformance/` exists.

`payments.proto` is compiled. The server's base class and the client's stub are both
generated from those bytes, so the code cannot disagree with the contract. There is no
drift to test for, because there is no gap to drift across.

That is the honest case for gRPC on an internal hop, and it is a stronger argument than
the one about payload size.

## Compare with what you had

[`../monolith/API.md`](../monolith/API.md) describes the same resources in prose. It is
clear, accurate, and completely inert: you cannot generate a client from it, diff it
meaningfully in review, or fail a build with it.

The gap between that file and this directory is the entire session.
