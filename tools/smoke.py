#!/usr/bin/env python3
"""Contract check for any implementation of the store.

    python tools/smoke.py http://localhost:8080

Language-neutral by design: it speaks HTTP and nothing else, uses only the standard
library, and has no idea whether it is talking to Python, Java, TypeScript, C#, Go or
Ruby. That is the point — the contract is the thing all six have in common, and this
script is what makes "they behave identically" a claim you can check rather than one
you have to trust.

It is also how you join in if your language is not one of the six: implement the API
in `monolith/API.md`, point this at it, and if it passes you are in the system.

Session 3 grows this into a conformance suite that runs against the three services.
The tests marked ATOMICITY are the ones with no equivalent over there — see the note
above them for why that absence is the lesson rather than a gap.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"

passed: list[str] = []
failed: list[str] = []


def request(method: str, path: str, body: dict | None = None) -> tuple[int, Any, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("content-type", "application/json")
    # Header field names are case-insensitive (RFC 9110 §5.1) and the six
    # implementations genuinely disagree: uvicorn sends `content-type`, Spring sends
    # `Content-Type`. A contract checker that cares about the difference is testing
    # its own assumptions rather than the contract, so normalise once, here.
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read().decode()
            headers = {k.lower(): v for k, v in response.headers.items()}
            return response.status, (json.loads(raw) if raw else None), headers
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        headers = {k.lower(): v for k, v in exc.headers.items()}
        return exc.code, (json.loads(raw) if raw else None), headers


def check(name: str, condition: bool, detail: str = ""):
    if condition:
        passed.append(name)
        print(f"  \033[32mPASS\033[0m  {name}")
    else:
        failed.append(name)
        print(f"  \033[31mFAIL\033[0m  {name}" + (f"\n          {detail}" if detail else ""))


def problem(name: str, status: int, payload, headers, want_status: int, want_type: str):
    """Every error in this API is RFC 9457 Problem Details. Verify the whole envelope."""
    check(f"{name}: status {want_status}", status == want_status, f"got {status}")
    check(
        f"{name}: content-type problem+json",
        "application/problem+json" in headers.get("content-type", ""),
        f"got {headers.get('content-type')!r}",
    )
    check(
        f"{name}: type ends with {want_type}",
        isinstance(payload, dict) and str(payload.get("type", "")).endswith(want_type),
        f"got {payload.get('type') if isinstance(payload, dict) else payload!r}",
    )
    check(
        f"{name}: envelope has title/status/detail",
        isinstance(payload, dict)
        and all(k in payload for k in ("title", "status", "detail"))
        and payload.get("status") == want_status,
        f"got {payload!r}",
    )


def stock_of(sku: str) -> int:
    _, product, _ = request("GET", f"/v1/products/{sku}")
    return product["stock"]


print(f"\nContract check against {BASE}\n")

# --- health ------------------------------------------------------------------
status, payload, _ = request("GET", "/health")
check("health: 200", status == 200, f"got {status}")
check("health: status ok", isinstance(payload, dict) and payload.get("status") == "ok")
check("health: names its implementation", bool(payload.get("implementation")))
impl = payload.get("implementation", "?")

# --- catalog -----------------------------------------------------------------
status, page, _ = request("GET", "/v1/products")
check("products: 200", status == 200, f"got {status}")
check("products: 8 seeded items", len(page["items"]) == 8, f"got {len(page['items'])}")
check("products: single page has no cursor", page["next_cursor"] is None)
check(
    "products: item shape",
    set(page["items"][0]) == {"sku", "name", "price_cents", "stock"},
    f"got {sorted(page['items'][0])}",
)
check(
    "products: sorted by sku",
    [i["sku"] for i in page["items"]] == sorted(i["sku"] for i in page["items"]),
)

status, first_page, _ = request("GET", "/v1/products?limit=3")
check("products: limit honoured", len(first_page["items"]) == 3)
check("products: cursor returned when more remain", bool(first_page["next_cursor"]))

seen = [i["sku"] for i in first_page["items"]]
cursor = first_page["next_cursor"]
while cursor:
    _, nxt, _ = request("GET", f"/v1/products?limit=3&cursor={cursor}")
    seen += [i["sku"] for i in nxt["items"]]
    cursor = nxt["next_cursor"]
check("products: full cursor walk yields every sku exactly once",
      sorted(seen) == sorted(set(seen)) and len(seen) == 8, f"got {len(seen)}: {seen}")

status, product, _ = request("GET", "/v1/products/BNS-005")
check("product: 200", status == 200, f"got {status}")
check("product: correct price", product["price_cents"] == 1800, f"got {product['price_cents']}")

status, payload, headers = request("GET", "/v1/products/ZZZ-999")
problem("unknown product", status, payload, headers, 404, "product-not-found")

# --- checkout, the happy path ------------------------------------------------
beans_before = stock_of("BNS-005")
grinder_before = stock_of("GRD-002")

status, order, headers = request(
    "POST", "/v1/orders",
    {"items": [{"sku": "GRD-002", "qty": 1}, {"sku": "BNS-005", "qty": 2}]},
)
check("checkout: 201", status == 201, f"got {status}: {order}")
check("checkout: Location header", headers.get("location", "").endswith(order["id"]),
      f"got {headers.get('location')!r}")
check("checkout: CONFIRMED", order["status"] == "CONFIRMED", f"got {order['status']}")
check("checkout: total is 1x18900 + 2x1800", order["total_cents"] == 22500,
      f"got {order['total_cents']}")
check("checkout: payment approved", order["payment"]["status"] == "APPROVED")
check("checkout: auth code present", bool(order["payment"]["auth_code"]))

lines = {line["sku"]: line for line in order["lines"]}
check("checkout: line copies the product name", lines["BNS-005"]["name"] == "Single Origin Beans",
      f"got {lines['BNS-005']['name']!r}")
check("checkout: line copies the unit price", lines["BNS-005"]["unit_cents"] == 1800)
check("checkout: stock decremented", stock_of("BNS-005") == beans_before - 2,
      f"{beans_before} -> {stock_of('BNS-005')}")

order_id = order["id"]
status, fetched, _ = request("GET", f"/v1/orders/{order_id}")
check("get order: 200", status == 200, f"got {status}")
check("get order: same total", fetched["total_cents"] == 22500)
check("get order: same lines", len(fetched["lines"]) == 2)

status, payload, headers = request("GET", "/v1/orders/does-not-exist")
problem("unknown order", status, payload, headers, 404, "order-not-found")

# --- ATOMICITY: a declined payment must undo the stock reservation -----------
# This is the test that justifies the whole bootcamp. Ordering ROA-008 costs more
# than the decline threshold, so the charge fails AFTER stock has been reserved and
# the order rows have been written. One ROLLBACK undoes all of it.
#
# Now the part worth arguing about. On Saturday, catalog and orders are separate
# services with separate databases and no ROLLBACK spans them — so the split system
# does not attempt this at all. Its catalog is read-only: orders asks for a price and
# never touches stock.
#
# That is not the services cheating. It is the cheapest correct answer to a
# distributed transaction, and the one most teams should reach for first: move the
# work out of the request, or do not split there. Buying this guarantee back needs a
# saga with a compensating action that survives a crash between two calls, plus
# reservations that expire when nothing arrives to confirm them — a module's worth of
# machinery for a line of SQL you already had.
#
# So this check has no counterpart in services/. Notice the absence, and notice what
# it cost to avoid.
roaster_before = stock_of("ROA-008")
status, payload, headers = request("POST", "/v1/orders", {"items": [{"sku": "ROA-008", "qty": 1}]})
problem("ATOMICITY declined payment", status, payload, headers, 402, "payment-declined")
check("ATOMICITY: reserved stock was rolled back", stock_of("ROA-008") == roaster_before,
      f"{roaster_before} -> {stock_of('ROA-008')} — the reservation leaked")

# --- checkout, the designed failures -----------------------------------------
status, payload, headers = request("POST", "/v1/orders", {"items": [{"sku": "NOPE-000", "qty": 1}]})
problem("checkout unknown sku", status, payload, headers, 404, "product-not-found")

status, payload, headers = request("POST", "/v1/orders", {"items": [{"sku": "MUG-007", "qty": 99999}]})
problem("checkout beyond stock", status, payload, headers, 409, "insufficient-stock")

status, payload, headers = request("POST", "/v1/orders", {"items": []})
problem("checkout empty basket", status, payload, headers, 400, "validation-failed")

status, payload, headers = request("POST", "/v1/orders", {"items": [{"sku": "MUG-007", "qty": 0}]})
problem("checkout zero quantity", status, payload, headers, 400, "validation-failed")

# --- cancel ------------------------------------------------------------------
status, cancelled, _ = request("POST", f"/v1/orders/{order_id}/cancel")
check("cancel: 200", status == 200, f"got {status}")
check("cancel: CANCELLED", cancelled["status"] == "CANCELLED", f"got {cancelled['status']}")
check("cancel: stock returned", stock_of("BNS-005") == beans_before,
      f"expected {beans_before}, got {stock_of('BNS-005')}")
check("cancel: grinder stock returned", stock_of("GRD-002") == grinder_before)

status, payload, headers = request("POST", f"/v1/orders/{order_id}/cancel")
problem("cancel twice", status, payload, headers, 409, "order-not-cancellable")

status, payload, headers = request("POST", "/v1/orders/does-not-exist/cancel")
problem("cancel unknown order", status, payload, headers, 404, "order-not-found")

# --- verdict -----------------------------------------------------------------
GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"
tally_colour = RED if failed else RESET
print(f"\n  {impl}: {GREEN}{len(passed)} passed{RESET}, "
      f"{tally_colour}{len(failed)} failed{RESET}\n")
if failed:
    for name in failed:
        print(f"    - {name}")
    print()
sys.exit(1 if failed else 0)
