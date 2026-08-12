# Contracts — Session 2

Empty on purpose. **You** design these on Saturday.

Session 2 is a design exercise: in pairs, you specify the orders API — resources,
verbs, status codes, the error envelope, whether create takes an idempotency key, and
what cancelling an already-shipped order returns. The published contracts land here
afterwards, so that what you argued about and what shipped can be compared.

By the end of Session 2 this directory holds:

| File | What it pins down |
|------|-------------------|
| `catalog.v1.yaml` | OpenAPI 3.1. The REST contract the world sees |
| `orders.v1.yaml` | OpenAPI 3.1. Checkout, cancel, and the idempotency story |
| `payments.v1.proto` | protobuf. The internal contract, where field *numbers* are the API |
| `problem.md` | The one RFC 9457 error envelope everything shares |

Until then, [`../monolith/API.md`](../monolith/API.md) is the informal version — what
the six implementations already agree on, written down after the fact. Read it before
Saturday and notice what it does *not* let you do: you cannot generate a client from
it, you cannot diff it in review, and nothing stops an implementation drifting from it
except a test suite someone remembered to run.

Closing that gap is the entire point of Session 2.
