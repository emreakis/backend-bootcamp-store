# Session 2 — Design the contract

**40 minutes · groups of three or four · one group presents its response table**

On Wednesday your group chose a module to cut out of the monolith and argued for it.
Today that argument has to be written down in a form a machine can read and another team
can build against.

You will design one contract before looking at ours, then diff the two. The
disagreements are the session.

> **Did not make Session 1, or want a fresh start?** Take the checkout path:
> `POST /v1/orders` is the arrow this exercise designs. Everything below assumes it.

```bash
git clone https://github.com/emreakis/backend-bootcamp-store
cd backend-bootcamp-store
```

Do **not** open `contracts/orders.v1.yaml` until part 3. That is the answer sheet.

---

## 1 · Read one as a reviewer (8 min)

Open `contracts/catalog.v1.yaml`. It is the read side, it is the shorter of the two, and
every decision in it was made on purpose. Find where the file answers each of these —
the answers are all in the file, most of them in a `description:`:

- **Why a cursor rather than `?offset=20`?** What exactly goes wrong for a client on
  page 2 while somebody inserts a product?
- **`stock` is in the response. Nothing in this API reserves it.** Why is a read-only
  catalogue the *cheap* answer to a transaction that would have to span two services?
- **`security: []` is written out rather than left off.** Both mean the same thing to a
  machine. What does it mean to a reviewer, and why is that worth two extra characters?
- **The cursor is documented as opaque.** That is a promise in both directions. What did
  the service get in exchange for making it — and what is the name of the law that
  explains why the paragraph is there at all?

Then one with no answer in the file: **should `stock` be in a public API?** It tells
every competitor what you are holding. That is a business decision wearing a technical
costume, and somebody has to make it on the record.

## 2 · Design the write side (18 min)

Now the hard one, with the file closed.

Your group is designing `POST /v1/orders`. It prices the basket against catalog, charges
the card through payments, and only then writes an order. Produce two things.

**The request.** Path, method, body shape. Any headers? Justify each one.

**The response table.** This is the deliverable. Every row is a decision, and a row you
cannot fill in is a decision you were about to leave to whoever writes the code:

| When | Status | Body | Headers |
|---|---|---|---|
| The order was placed | | | |
| Empty basket, or `qty: 0` | | | |
| A sku in the basket does not exist | | | |
| The card was declined | | | |
| **Payments does not answer** | | | |

Rules of the exercise:

1. **Every non-2xx uses one envelope.** Design it once, in one place, and say what is in
   it. Six different error shapes is six times the client code.
2. **The last row is not optional.** Most contracts document only the failures the
   service causes itself. Yours has a dependency now.
3. For each 4xx/5xx, say out loud **whose fault it is**: 4xx means the caller should
   change the request, 5xx means it should not. If you cannot decide, that row is
   interesting and you should mark it.

Then the question the contract does not ask but Saturday afternoon will: **is this
endpoint safe to send twice?** If your answer needs a header, put it in the request
section and decide whether it is required.

## 3 · Diff against ours (8 min)

Open `contracts/orders.v1.yaml`. Read your table against it. Three disagreements come up
almost every time — the file names them in its own header:

- **Does create take an idempotency key, and is it required?** Ours is optional, with a
  written reason you are allowed to disagree with.
- **What does cancelling an already-cancelled order return?** Ours is a `409`, and it
  argues for it. Yours may be `400`, `404`, or a cheerful `200`.
- **What does the store return when payments is down?** Ours is a `503` with
  `Retry-After` and a promise that no charge was made.

There is more than one defensible answer to each. What is not defensible is leaving them
undecided until a client hits them in production.

Lint yours if you wrote YAML:

```bash
npx @redocly/cli lint contracts/orders.v1.yaml
npx @redocly/cli preview-docs contracts/orders.v1.yaml     # read it as a human would
```

That passing tells you the document is well formed. It tells you **nothing** about
whether the prose describes the API accurately, and that gap is most of this session.

### The traps

**`DELETE /v1/orders/{id}` for cancel.** It reads beautifully and it is wrong here.
Cancelling is not deleting: the order still exists, still has to be reportable, and its
money still has to be accounted for. The resource survives, its *state* changes, and
naming the transition in the path is the honest version.

**Payments is down, so it is a 500.** Or a 502. Or — and somebody always proposes this —
a `200` with `{"status": "pending"}`. Ask that group what a well-behaved client does
next, and how it knows when to come back. `Retry-After` is the part everyone forgets,
and without it every client in the stampede retries at the same moment.

## 4 · The one that is not a document (6 min)

Open `contracts/proto/bootcamp/payments/v1/payments.proto`. This is the internal hop —
orders to payments, never customer-facing.

**Both files describe an API. Only this one *is* the API.** The OpenAPI files are
documents that six hand-written implementations promise to satisfy, and nothing stops
them drifting except tests somebody remembered to run. This one is compiled: the
server's base class and the client's stub both come out of these bytes.

Two things to find, then one to argue about:

- **`reserved 5;`** — field 5 was `card_token` and its number is retired forever. Say
  why reusing it would be worse than leaving a gap. The failure mode is not an error.
- **`CHARGE_STATUS_UNSPECIFIED = 0`** — the zero value has to be the unknown one. What
  breaks if `APPROVED` were 0?

And the argument: **a declined card comes back `OK`.** Not `PERMISSION_DENIED`, not any
gRPC error status — a normal response whose `status` field says `DECLINED`. Somebody in
the room will want it to be an error code, because a decline feels like a failure.

They should be ready to say what happens when orders retries it.

---

## What happens next

Session 3 runs the system these contracts describe: three services, six languages each,
every combination. Then it breaks the last row of your table on purpose — payments stops
answering — and you find out that a `503` is not something a contract gives you. It is
something you build.

Bring the row you could not fill in.
