# The `solution` branch

This branch is `main` with the four Session 3 exercises implemented, in all six
languages. Nothing else differs.

```bash
git diff main solution -- services/orders/java          # or python, typescript, csharp, go, ruby
git diff main solution --stat                           # all six at once
```

Read one language's diff and you have the answer. Read two and you start seeing which
parts are the idea and which parts are the library.

## Proving it

The same script asserts both states, which is the honest way to show that the exercises
did something:

```bash
cd services && docker compose up --build -d
cd ..

python conformance/contract.py                    # 87 checks, identical on both branches
python conformance/resilience.py --expect-fixed   # 13 checks, only green on this branch
```

On `main`, run `resilience.py` with no flag: it asserts that a slow payments service
hangs checkout, that a stopped one hangs it identically, and that `/health` answers `ok`
throughout. Those are passing tests describing a broken system. This branch is what makes
`--expect-fixed` true instead.

## What changed, and in what order

| # | File | What arrived |
|---|------|--------------|
| 3.1 | the payments client | **A deadline.** Worth more than the other three together |
| 3.2 | the payments client | A bounded retry with backoff, for two status codes only |
| 3.3 | the payments client | A circuit breaker with a half-open state |
| 3.4 | the catalog client | Connect and read timeouts |

**3.1 first, always.** Delete the retry and the breaker and this service still degrades
honestly; delete the deadline and nothing else can save it. Before it, "payments is down"
and "payments is slow" are the same event — a hang — because a caller with no deadline
cannot tell those apart. After it, they are different failures, which is what makes the
other three exercises mean anything.

**3.2 is only legal because of the idempotency key.** `ChargeRequest` carries one, and
payments returns the original response for a key it has seen. Take that field away and
the retry loop is a double-billing bug that appears under load. Retries are also bounded
and backed off, because retrying into an overloaded service adds load to the exact system
that is failing from load.

**3.3 needs its half-open state.** A breaker that opens and never closes is a permanent
outage you built yourself. After `BREAKER_RESET_MS` exactly one probe goes through; it
closes on success and restarts the clock on failure.

**3.4 is the same problem, one hop earlier and much less dramatic.** A slow catalog
blocks the same threads as a slow payments service, and does it first.

## The decision every language forces you to make

The deadline here is **per attempt**, so the worst case is three attempts plus backoff:
`3 × 2000 ms + 250 ms ≈ 6.25 s`. Whoever calls checkout has their own budget, and six
seconds may already be over it.

The other defensible design is one deadline shared by every attempt — compute the instant
once, outside the loop. That keeps the promise at 2 s, but a slow dependency spends the
whole budget on attempt one and the retries never happen.

Which is the lesson underneath both: **retries fix transient failures, not slow ones.**
Node and Ruby make this choice visible because they want an absolute `Date`/`Time`, so
the difference is literally whether one line sits inside the loop or above it. Python, Go
and Java take a duration and hide it.

## Three things the six do not agree about

**.NET reports your own deadline as `Cancelled`.** When the deadline fires, Grpc.Net gives
up locally *and* payments — watching the same deadline, because deadlines propagate —
resets the HTTP/2 stream. Whichever arrives first names the failure: win the race and you
get `DeadlineExceeded`, lose it and you get `Cancelled` wrapping the peer's RST_STREAM.
This showed up as a flaky test before anyone read the status code. `PaymentsClient.cs`
retries on the *cause* rather than the code for exactly this reason, and says so.

**Node needs no lock and the other five do.** The breaker's counter is shared mutable
state under concurrency everywhere except Node, which runs it on one thread. What Node has
instead is worse: no thread pool to exhaust means a hung dependency shows up as memory
quietly filling with pending promises while the process still reports itself healthy.

**Only Ruby makes you name two timeouts.** `open_timeout` is "I cannot reach this host";
`read_timeout` is "this host accepted my connection and then went quiet". Different
failures, different causes, and only the second is what `docker compose pause catalog`
produces. Every other language here has one knob by default and hides the distinction in
a transport object.
