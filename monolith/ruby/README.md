# The store — Ruby (Sinatra)

```bash
bundle install && bundle exec ruby app.rb    # from this directory
python tools/smoke.py http://localhost:8080  # from the repo root
```

Needs a C compiler: `puma` depends on `nio4r`, which ships no precompiled gem. Or, with
only Docker, from the repo root: `MONOLITH_IMPL=ruby docker compose up --build`

## Files

| File | What it is |
|------|-----------|
| `lib/config.rb` | Every setting, read from the environment |
| `lib/errors.rb` | Domain outcomes — the failures the business decided can happen |
| `lib/database.rb` | The one connection, and `transaction` |
| `lib/catalog.rb` | **MODULE.** Owns `products` |
| `lib/payments.rb` | **MODULE.** Owns `payments`. No routes of its own |
| `lib/orders.rb` | **MODULE.** Owns `orders` + `order_lines`. The orchestrator |
| `app.rb` | The HTTP layer — the only file that knows what a status code is |

## What is idiomatic here

**This is the shortest of the six, and the least protected.** `private_class_method`
hides a helper, but nothing whatsoever stops another file from opening the database and
writing `SELECT * FROM products`. Go, Java and C# make that a compile error; Nest makes
it a wiring error; Ruby makes it a code review.

That makes this implementation the most honest illustration of what a modular monolith
actually is: **a set of rules a team agreed to keep.** Every monolith that rotted into a
big ball of mud did so one reasonable-looking shortcut at a time, and in a language
where the shortcut compiles.

Read `lib/catalog.rb` and ask how you would *notice* if someone broke the rule next
sprint. Whatever you answer — a linter, a test, a review checklist, a directory
convention — is the thing that has to exist before the split in Session 3 is possible.

**`Database.transaction` captures the block's result deliberately.** sqlite3's own
`transaction` returns `true`, not the block value, and a bare `return` inside it would
jump out past the commit. A small trap, and a real one.

**Sinatra's friendly error pages are switched off.** `set :show_exceptions, false` means
the `error DomainError` handler is the only way a failure leaves this process — so every
error really does get the RFC 9457 envelope.
