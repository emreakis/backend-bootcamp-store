# Session 3 — Break it, then fix it properly

**50 minutes · pairs, at a keyboard · everyone measures, and the numbers will disagree**

The contracts from Session 2 are now three running services. Same store, same data, same
behaviour — three processes, two databases, two protocols.

You are going to take payments away and watch a healthy orders service die of somebody
else's outage. Then you will fix it, in the right order, and prove each fix with a test.

> **Do this before you sit down.** A first `docker compose up --build` pulls a lot, and
> a slow download should not cost you the exercise.

```bash
git clone https://github.com/emreakis/backend-bootcamp-store
cd backend-bootcamp-store/services
docker compose up --build -d
```

Pick your language for the orders service — that is where all the work is:

```bash
ORDERS_IMPL=go docker compose up --build -d     # python | java | typescript | csharp | go | ruby
```

`catalog` and `payments` can be any of the six and it makes no difference to you. That is
the point of the container being the interface, and it is worth swapping one mid-session
just to watch nothing happen.

---

## 0 · Establish that it works (5 min)

```bash
curl -X POST localhost:8080/v1/orders -H 'content-type: application/json' \
     -H 'Idempotency-Key: mine-1' \
     -d '{"items":[{"sku":"GRD-002","qty":1},{"sku":"BNS-005","qty":2}]}'
```

Then, from the repo root:

```bash
python conformance/contract.py       # 87 checks, stdlib only
python conformance/resilience.py     # 8 checks — and read what they say
```

The second one takes a couple of minutes, because it spends real seconds waiting for
things that never arrive. Read the check names as they scroll rather than waiting it out.

It is green. Read the names of the checks that passed: they assert that a
slow payments service **hangs checkout**, and that orders reports itself perfectly
healthy while it does. Those are passing tests describing a broken system.

**Writing the broken behaviour down is the whole trick.** The alternative is not a
system without that behaviour; it is the same system with nobody's name on it.

## 1 · Three outages, and they are not the same (10 min)

```bash
PAYMENT_LATENCY_MS=30000 docker compose up -d payments   # SLOW: accepts, then holds
docker compose pause payments                            # BLACK HOLE: packets vanish
docker compose stop payments                             # DOWN: it depends
```

Between each, time a checkout and check `/health`:

```bash
time curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8080/v1/orders \
     -H 'content-type: application/json' -d '{"items":[{"sku":"GRD-002","qty":1}]}'
curl -s localhost:8080/health
```

Fill this in for **your** language:

| Break | What you expected | What you measured | `/health` said |
|---|---|---|---|
| slow (30 s latency) | | | |
| paused | | | |
| stopped | | | |

Two things to notice, and the second one is the exercise.

**`/health` says `ok` throughout.** It is right to. Orders is not sick — its dependency
is. A liveness check that called payments would make a payments outage into an orders
restart loop, removing capacity from a working service in the middle of an incident,
executed by the platform on your behalf.

**Now compare the last row with the pair next to you**, and make sure you are not both
running the same language. Measured across all six with no deadline anywhere:

| orders | how long a *stopped* payments takes to fail |
|---|---|
| C# | ~4 s |
| Python, Go, Ruby | ~20 s — the gRPC library's own connect timeout |
| Java, TypeScript | still waiting after 25 s |

**Same outage, same contract, four seconds to never.** Not one of those numbers was
chosen by anyone who works on this store. That is the argument for the deadline — and
note that 20 seconds is not the "fast" option, it is a hang with extra steps.

**Put payments back before you go on.** From here the conformance suite does its own
breaking — it pauses, stops and unpauses payments itself, and it opens by asserting that
a *healthy* checkout works. Hand it a stack in one piece before every run:

```bash
docker compose unpause payments ; docker compose up -d payments
```

When you want to break it by hand again, reach for `pause`. It is the only one of the
three that behaves identically in every language, which makes it the only one you can
trust a measurement from.

## 2 · Exercise 3.1 — a deadline (12 min)

Open your orders service's payments client. Four `TODO (exercise 3.x)` blocks; do this
one first.

> **`PAYMENTS_TIMEOUT_MS` is already in your config at 2000, and it is a policy, not a
> guess.** It means "the longest a checkout may wait on a charge". Nobody measured the
> payment provider to arrive at it.

Then:

```bash
docker compose up --build -d orders
python conformance/resilience.py --expect-fixed
```

Checks start flipping. **This one fix is worth more than the other three together** —
it is what converts a hang into an answer, and every remaining exercise is a refinement
of an answer you now actually produce.

If your language's client makes it hard to find where the deadline goes, that is
informative. Go puts it in the first argument of every generated method and will not let
you make the call without passing *something* — where `context.Background()` is one word
away and means forever.

## 3 · Exercise 3.2 — a bounded retry (10 min)

Before writing it, answer this: **why are you allowed to retry `Charge` at all?**

The answer is not "because it failed". Open
`contracts/proto/bootcamp/payments/v1/payments.proto` and find `idempotency_key`. A
repeat of a seen key returns the *original* response and takes no second payment. Retry
a call without that guarantee and you have not added resilience — you have added a
double-billing bug that only appears under load.

Bounded, with backoff, and with a reason for the bound.

### Then work out what your customer actually waits

You set a 2000 ms deadline. With `PAYMENTS_RETRY_MAX=2` — three attempts — and a 2000 ms
deadline **on each attempt**, the worst case a customer experiences is about **6.25 s**,
not 2. Check it against your own numbers.

That is the design question of the session, and it is genuinely open:

- **A deadline per attempt** is simple, and the total is whatever the arithmetic says.
- **One budget shared across all attempts** means the customer's wait is the number you
  actually chose — and the third attempt may get 200 ms, which is often not enough to be
  worth making.

The `solution` branch picks per-attempt and says so. Decide which you would ship, and be
ready to say why.

## 4 · Exercise 3.3 — a circuit breaker (10 min)

Retries make an outage worse. Every checkout is now making three calls to a service that
is already unwell, and you have tripled the load on the thing you are waiting to recover.

The breaker's job is not to make one call fail better. It is to **stop making the call**,
so payments gets room to come back and your customers get a fast, designed failure
instead of a slow, accidental one.

Then unpause it and watch the last check:

```bash
docker compose unpause payments
python conformance/resilience.py --expect-fixed     # 17 checks
```

`recovery: checkout works again without restarting orders` is the half-open state doing
its job. A breaker that never closes again is just an outage you wrote yourself.

## 5 · Exercise 3.4 — the other hop (5 min, or on the train home)

`catalog_client` has the same problem, one hop earlier and much less dramatic. Do it for
the symmetry, and for the habit: **the default for a network call is forever, in every
language, unless somebody typed a number.**

### The traps

**Retries before a deadline.** Somebody will do 3.2 first because it feels more like
engineering. With no deadline, a retry cannot fire — the first attempt never returns. If
it did, you would have turned one hang into three.

**A breaker that opens on declines.** A declined card is a `ChargeResponse` with
`status: DECLINED` and a gRPC status of `OK` — a successful call with an unwelcome
answer. Count it as a failure and a busy Friday of legitimately declined cards will trip
your breaker and stop the store selling anything.

**Retrying a 402.** Same root cause, one layer up. `4xx` means *change the request*. No
number of retries will change that card's mind.

---

## The answer sheet

```bash
git diff main solution -- services/orders/go        # or your language
```

All four TODOs, filled in, in every language, with the reasoning in
[`SOLUTION.md`](https://github.com/emreakis/backend-bootcamp-store/blob/solution/SOLUTION.md).
Read it *after* you have your own version, not instead of it.

## What you built, and what is still open

You converted a hang into a 503 with a `Retry-After` — the row of the Session 2 response
table nobody could fill in.

What you did **not** get back is the monolith's transaction. There is still no atomicity
between charging the card and writing the order: if the process dies between them, a
customer has paid for an order that does not exist. That hole is real and it is left
visible on purpose. The honest answers — an outbox, a reconciliation job, a saga with a
compensating action — are the next thing after this bootcamp.

The monolith closed it with one keyword. That was the bill, and you have now read it.
