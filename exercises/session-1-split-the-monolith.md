# Session 1 — Split this monolith

**20 minutes · groups of three or four · one group reports back on question 3**

You have a working store in front of you. One process, one database, one deployment,
three modules. Your job is not to admire it — it is to decide, with reasons, where you
would cut it, and what that cut would cost.

Pick whichever language you are most fluent in; all six are the same program.

```bash
MONOLITH_IMPL=python docker compose up --build     # or java | typescript | csharp | go | ruby
```

**Start that now and leave it running in a second terminal.** The first build pulls a
base image and a language toolchain; on shared wifi that is minutes, and Java pulls the
most. Only the proof in part 2 needs it — parts 1 and 3 are reading and arguing, so
begin them while it builds.

Read `db/schema.sql` first. It is forty lines and it tells you more about this system
than the code does.

---

## 1 · Find the seams (5 min)

Open the three module files in your language — `catalog`, `orders`, `payments` — and
answer for each:

- **What is its job, in one sentence?** If the sentence needs an "and", you may have
  found two modules.
- **Which tables does it own?** `db/schema.sql` marks every table with an owner.
- **Who calls it?** Search for the module's name in the other two.

Then find the one module nobody calls. Why does it have no HTTP endpoints of its own?
What does that suggest about how it should be exposed if it ever becomes a service?

## 2 · Draw the bill (7 min)

Three things in this codebase are free today and expensive on Saturday. Find all three
by reading, not guessing:

| # | Find it in | What to look for |
|---|-----------|------------------|
| 1 | `db/schema.sql` | Two foreign keys marked `LOST BY SATURDAY`. Why can neither survive a split? |
| 2 | `checkout` in the orders module | One construct that makes three modules' writes all-or-nothing. Name it. |
| 3 | `reserve` in the catalog module | It cannot time out, cannot be retried, cannot answer twice. Why not? |

Now prove the second one to yourself. `ROA-008` costs more than the payment stub will
approve, so this checkout fails **after** stock has been reserved and the order rows
have been written:

```bash
curl -s localhost:8080/v1/products/ROA-008          # note the stock
curl -s -X POST localhost:8080/v1/orders \
     -H 'content-type: application/json' \
     -d '{"items":[{"sku":"ROA-008","qty":1}]}'     # 402, payment declined
curl -s localhost:8080/v1/products/ROA-008          # stock is untouched
```

Nobody wrote code to put that stock back. **Who did?**

## 3 · Make the cut (8 min)

Your organisation has grown to four teams and checkout falls over on sale day. You have
been asked to split exactly one module out of this monolith first.

Decide as a group, and be ready to defend it in three sentences:

- **Which module goes first, and why that one?**
- **What data does it take with it?** Name the tables. Then name the queries that
  currently join across the cut — those are the ones that become network calls.
- **What breaks the first time it is down?** Be specific: which endpoint, which user
  action, what does the customer see?
- **What do you have to build that you do not need today?** Every group should end up
  naming at least two of: retries, timeouts, idempotency keys, a compensating action, a
  circuit breaker, distributed tracing.

### The trap

At least one group will propose splitting `payments` first, because it is the smallest
and has no HTTP surface. That is a defensible answer — and it also puts a network call
in the middle of a transaction that currently cannot half-succeed. Whoever proposes it
should be ready to say what happens when the charge succeeds and the reply is lost.

There is no right answer here. There is only the bill, and whether you read it before
signing.

---

## What happens next

Bring your answer to Session 2. The cut your group chose is the arrow we design a
contract for, and in Session 3 you will run the split system, break it on purpose, and
find out which of your predictions were right.
