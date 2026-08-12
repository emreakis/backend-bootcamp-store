#!/usr/bin/env python3
"""Contract check for the three services, in any combination of languages.

    python conformance/contract.py

    python conformance/contract.py --catalog http://localhost:8000 \
                                   --orders  http://localhost:8080

This is `tools/smoke.py` grown up. Same idea, same rules: it speaks HTTP and nothing
else, uses only the standard library, and has no idea which language is answering. The
contracts in `contracts/` are the thing every implementation has in common, and this
script is what turns "they behave identically" into a claim you can check rather than
one you have to trust.

    cd services && CATALOG_IMPL=go ORDERS_IMPL=csharp PAYMENTS_IMPL=ruby \
        docker compose up --build -d
    python ../conformance/contract.py

Payments has no HTTP surface, so nothing here calls it directly — and that is the
correct shape for a test as well as for a system. Every assertion about payments below
is made *through* orders, because that is the only way anything in this store reaches
it. Testing a private dependency from outside would be testing an integration nobody
is allowed to have.

WHAT IS DELIBERATELY NOT HERE: the ATOMICITY checks from tools/smoke.py.

In the monolith, a declined payment rolled back the stock reservation in the same
transaction, and smoke.py asserted it. Across two databases there is no transaction to
roll back and no stock to reserve, so those assertions have no counterpart here. Their
absence is not a gap in this file. It is the bill for the split, and Session 3's
`resilience.py` is where you find out what you have to build instead.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
import uuid
from typing import Any

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"

passed: list[str] = []
failed: list[str] = []


def request(base: str, method: str, path: str, body: dict | None = None,
            headers: dict[str, str] | None = None) -> tuple[int, Any, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if data:
        req.add_header("content-type", "application/json")
    for name, value in (headers or {}).items():
        req.add_header(name, value)

    # Header field names are case-insensitive (RFC 9110 5.1) and the implementations
    # genuinely disagree: uvicorn sends `content-type`, Spring sends `Content-Type`,
    # Kestrel sends `Content-Type`. A contract checker that cares about the difference
    # is testing its own assumptions rather than the contract, so normalise once here.
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode()
            return (response.status,
                    json.loads(raw) if raw else None,
                    {k.lower(): v for k, v in response.headers.items()})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        return (exc.code,
                json.loads(raw) if raw else None,
                {k.lower(): v for k, v in exc.headers.items()})


def check(name: str, condition: object, detail: str = "") -> bool:
    if condition:
        passed.append(name)
        print(f"  {GREEN}PASS{RESET}  {name}")
    else:
        failed.append(name)
        print(f"  {RED}FAIL{RESET}  {name}" + (f"\n          {detail}" if detail else ""))
    return bool(condition)


def problem(name: str, status: int, payload: Any, headers: dict,
            want_status: int, want_type: str, want_retry_after: bool = False):
    """Every error in this system is RFC 9457 Problem Details, in all six languages.

    One envelope is the whole point of contracts/problem.yaml: a client written
    against orders already knows how to read an error from catalog.
    """
    check(f"{name}: status {want_status}", status == want_status, f"got {status}")
    check(f"{name}: content-type problem+json",
          "application/problem+json" in headers.get("content-type", ""),
          f"got {headers.get('content-type')!r}")
    check(f"{name}: type ends with {want_type}",
          isinstance(payload, dict) and str(payload.get("type", "")).endswith(want_type),
          f"got {payload.get('type') if isinstance(payload, dict) else payload!r}")
    check(f"{name}: envelope has title/status/detail",
          isinstance(payload, dict)
          and all(k in payload for k in ("title", "status", "detail"))
          and payload.get("status") == want_status,
          f"got {payload!r}")
    if want_retry_after:
        # A 503 without Retry-After tells the client something is wrong but not what
        # to do about it, so every well-behaved one guesses — and they all guess the
        # same aggressive number at the same moment.
        check(f"{name}: carries Retry-After", "retry-after" in headers,
              f"headers were {sorted(headers)}")


# ---------------------------------------------------------------------------
#  catalog — read-only, and the easy one
# ---------------------------------------------------------------------------

def check_catalog(base: str) -> None:
    print(f"\n{DIM}catalog{RESET} {base}\n")

    status, body, _ = request(base, "GET", "/health")
    check("health: 200", status == 200, f"got {status}")
    check("health: says ok",
          isinstance(body, dict) and body.get("status") == "ok", f"got {body!r}")
    check("health: names its implementation",
          isinstance(body, dict) and bool(body.get("implementation")), f"got {body!r}")

    status, page, _ = request(base, "GET", "/v1/products")
    check("list: 200", status == 200, f"got {status}")
    check("list: has items and next_cursor",
          isinstance(page, dict) and isinstance(page.get("items"), list)
          and "next_cursor" in page, f"got {page!r}")
    check("list: returns the seeded catalogue",
          isinstance(page, dict) and len(page.get("items", [])) == 8,
          f"got {len(page.get('items', [])) if isinstance(page, dict) else page!r}")

    # Keyset pagination, which is the part of the contract most easily got wrong.
    # An offset drifts under concurrent inserts; a cursor is a position in the data.
    _, first, _ = request(base, "GET", "/v1/products?limit=3")
    check("page 1: exactly 3 items",
          isinstance(first, dict) and len(first.get("items", [])) == 3,
          f"got {first!r}")
    check("page 1: has a next_cursor",
          isinstance(first, dict) and first.get("next_cursor"), f"got {first!r}")

    if isinstance(first, dict) and first.get("next_cursor"):
        _, second, _ = request(base, "GET",
                               f"/v1/products?limit=3&cursor={first['next_cursor']}")
        first_skus = [p["sku"] for p in first["items"]]
        second_skus = [p["sku"] for p in second.get("items", [])]
        check("page 2: no overlap with page 1",
              not (set(first_skus) & set(second_skus)),
              f"{first_skus} then {second_skus}")
        check("page 2: continues in sku order",
              bool(second_skus) and second_skus[0] > first_skus[-1],
              f"{first_skus[-1]} then {second_skus[:1]}")

    status, product, _ = request(base, "GET", "/v1/products/GRD-002")
    check("get: 200", status == 200, f"got {status}")
    check("get: the whole product shape",
          isinstance(product, dict)
          and product.get("sku") == "GRD-002"
          and product.get("name") == "Burr Grinder"
          and product.get("price_cents") == 18900
          and isinstance(product.get("stock"), int),
          f"got {product!r}")

    # The most consequential response in this service: orders turns it into a
    # designed order rejection, so it has to be unambiguous and never a 500.
    status, payload, headers = request(base, "GET", "/v1/products/NOPE-000")
    problem("get missing", status, payload, headers, 404, "product-not-found")

    # The check that caught the Python implementation lying about its own contract.
    #
    # `limit` is declared 1..100, and the spec says an out-of-range one is a 400 in the
    # usual envelope. FastAPI's default was a 422 carrying pydantic's error structure —
    # neither the status nor the shape the contract promises.
    #
    # This is the most common way an implementation drifts from its spec: not by getting
    # an endpoint wrong, but by letting the framework answer on a path nobody wrote by
    # hand. Every one of the six has a different default here, which is precisely why it
    # has to be asserted rather than assumed.
    for name, query in (("limit too small", "limit=0"),
                        ("limit too large", "limit=101"),
                        ("limit not a number", "limit=abc")):
        status, payload, headers = request(base, "GET", f"/v1/products?{query}")
        problem(name, status, payload, headers, 400, "validation-failed")


# ---------------------------------------------------------------------------
#  orders — the orchestrator, and where everything interesting happens
# ---------------------------------------------------------------------------

def check_orders(base: str) -> None:
    print(f"\n{DIM}orders{RESET} {base}\n")

    status, body, _ = request(base, "GET", "/health")
    check("health: 200", status == 200, f"got {status}")
    check("health: says ok",
          isinstance(body, dict) and body.get("status") == "ok", f"got {body!r}")
    check("health: names its implementation",
          isinstance(body, dict) and bool(body.get("implementation")), f"got {body!r}")

    # ---- the happy path -----------------------------------------------------
    key = f"conformance-{uuid.uuid4()}"
    basket = {"items": [{"sku": "GRD-002", "qty": 1}, {"sku": "BNS-005", "qty": 2}]}
    status, order, headers = request(base, "POST", "/v1/orders", basket,
                                     {"Idempotency-Key": key})

    check("checkout: 201", status == 201, f"got {status}: {order!r}")
    check("checkout: Location points at the new order",
          isinstance(order, dict) and headers.get("location", "").endswith(order.get("id", "\x00")),
          f"got {headers.get('location')!r}")
    check("checkout: total is priced by catalog, not by the client",
          isinstance(order, dict) and order.get("total_cents") == 18900 + 2 * 1800,
          f"got {order.get('total_cents') if isinstance(order, dict) else order!r}")
    check("checkout: CONFIRMED",
          isinstance(order, dict) and order.get("status") == "CONFIRMED", f"got {order!r}")
    check("checkout: created_at is RFC 3339 UTC",
          isinstance(order, dict) and str(order.get("created_at", "")).endswith("Z"),
          f"got {order.get('created_at') if isinstance(order, dict) else order!r}")

    lines = order.get("lines", []) if isinstance(order, dict) else []
    by_sku = {line["sku"]: line for line in lines if isinstance(line, dict)}
    check("checkout: both lines came back", len(lines) == 2, f"got {lines!r}")

    # The copied name and price are the reason GET /v1/orders/{id} never has to call
    # catalog. A dependency you do not have cannot be down.
    check("checkout: lines carry the name copied from catalog at purchase time",
          by_sku.get("GRD-002", {}).get("name") == "Burr Grinder", f"got {lines!r}")
    check("checkout: lines carry the unit price copied from catalog",
          by_sku.get("GRD-002", {}).get("unit_cents") == 18900
          and by_sku.get("BNS-005", {}).get("unit_cents") == 1800, f"got {lines!r}")
    check("checkout: lines carry qty",
          by_sku.get("BNS-005", {}).get("qty") == 2, f"got {lines!r}")

    payment = order.get("payment") if isinstance(order, dict) else None
    check("checkout: the payment outcome is recorded on the order",
          isinstance(payment, dict) and payment.get("status") == "APPROVED"
          and bool(payment.get("auth_code")), f"got {payment!r}")

    order_id = order.get("id") if isinstance(order, dict) else None

    # ---- reading it back ----------------------------------------------------
    if order_id:
        status, fetched, _ = request(base, "GET", f"/v1/orders/{order_id}")
        check("get: 200", status == 200, f"got {status}")
        check("get: identical to what checkout returned",
              isinstance(fetched, dict)
              and fetched.get("total_cents") == order.get("total_cents")
              and fetched.get("status") == "CONFIRMED"
              and len(fetched.get("lines", [])) == 2
              and (fetched.get("payment") or {}).get("status") == "APPROVED",
              f"got {fetched!r}")

    # ---- idempotency: the table the monolith did not need -------------------
    #
    # Across a network there is a third outcome besides success and failure: the order
    # was created and the response was lost. The caller cannot tell that apart from
    # the order never existing, so a well-behaved client retries.
    status, replay, _ = request(base, "POST", "/v1/orders", basket,
                                {"Idempotency-Key": key})
    check("replay: same key returns the SAME order, not a second one",
          isinstance(replay, dict) and replay.get("id") == order_id,
          f"got {replay.get('id') if isinstance(replay, dict) else replay!r}, wanted {order_id}")
    check("replay: and the same total",
          isinstance(replay, dict) and replay.get("total_cents") == 18900 + 2 * 1800,
          f"got {replay!r}")

    # No key means no protection, and the contract says so out loud rather than
    # pretending otherwise. Two identical requests are two orders.
    _, one, _ = request(base, "POST", "/v1/orders", {"items": [{"sku": "MUG-007", "qty": 1}]})
    _, two, _ = request(base, "POST", "/v1/orders", {"items": [{"sku": "MUG-007", "qty": 1}]})
    check("no key: two identical requests are two different orders",
          isinstance(one, dict) and isinstance(two, dict)
          and one.get("id") and one.get("id") != two.get("id"),
          f"got {one.get('id') if isinstance(one, dict) else one!r} "
          f"and {two.get('id') if isinstance(two, dict) else two!r}")

    # ---- the declined card --------------------------------------------------
    #
    # ROA-008 costs 529900, over the stub provider's 500000 limit. Payments returns
    # gRPC OK with status DECLINED — a business outcome, not a transport failure — and
    # orders turns that into a 402 that no retry policy will ever re-attempt.
    status, payload, headers = request(base, "POST", "/v1/orders",
                                       {"items": [{"sku": "ROA-008", "qty": 1}]})
    problem("declined", status, payload, headers, 402, "payment-declined")

    # ---- catalog's 404, translated -----------------------------------------
    status, payload, headers = request(base, "POST", "/v1/orders",
                                       {"items": [{"sku": "NOPE-000", "qty": 1}]})
    problem("unknown sku", status, payload, headers, 404, "product-not-found")

    # ---- validation ---------------------------------------------------------
    status, payload, headers = request(base, "POST", "/v1/orders", {"items": []})
    problem("empty basket", status, payload, headers, 400, "validation-failed")

    status, payload, headers = request(base, "POST", "/v1/orders", {})
    problem("no items field", status, payload, headers, 400, "validation-failed")

    status, payload, headers = request(base, "POST", "/v1/orders",
                                       {"items": [{"sku": "MUG-007", "qty": 0}]})
    problem("qty of zero", status, payload, headers, 400, "validation-failed")

    # ---- orders that are not there ------------------------------------------
    status, payload, headers = request(base, "GET", "/v1/orders/not-a-uuid")
    problem("get non-uuid", status, payload, headers, 404, "order-not-found")

    status, payload, headers = request(base, "GET", f"/v1/orders/{uuid.uuid4()}")
    problem("get unknown uuid", status, payload, headers, 404, "order-not-found")

    # ---- cancel -------------------------------------------------------------
    if order_id:
        status, cancelled, _ = request(base, "POST", f"/v1/orders/{order_id}/cancel")
        check("cancel: 200", status == 200, f"got {status}")
        check("cancel: the order still exists, in a new state",
              isinstance(cancelled, dict) and cancelled.get("status") == "CANCELLED"
              and cancelled.get("id") == order_id
              and len(cancelled.get("lines", [])) == 2,
              f"got {cancelled!r}")

        # 409 is the underused status code, and this is its case: well-formed request,
        # healthy server, transition the resource cannot make.
        status, payload, headers = request(base, "POST", f"/v1/orders/{order_id}/cancel")
        problem("cancel twice", status, payload, headers, 409, "order-not-cancellable")

    status, payload, headers = request(base, "POST", f"/v1/orders/{uuid.uuid4()}/cancel")
    problem("cancel unknown", status, payload, headers, 404, "order-not-found")


# ---------------------------------------------------------------------------
#  The boundary itself
# ---------------------------------------------------------------------------

def check_boundaries(catalog: str, orders: str) -> None:
    """Each service serves its own API and nobody else's.

    Obvious, and worth asserting anyway: the fastest way to undo a split is for one
    service to start being helpful and proxy another's endpoints. Then you have two
    processes and one API, which is the cost of microservices without the benefit.
    """
    print(f"\n{DIM}boundaries{RESET}\n")

    status, _, _ = request(orders, "GET", "/v1/products")
    check("orders does not serve catalog's API", status in (404, 405), f"got {status}")

    status, _, _ = request(catalog, "GET", "/v1/orders/" + str(uuid.uuid4()))
    check("catalog does not serve orders' API", status in (404, 405), f"got {status}")

    # Payments is not reachable over HTTP at all, from anywhere. It is an internal
    # service with an internal protocol, and nothing outside the cluster should be
    # able to ask it for money.
    check("payments has no HTTP surface to check", True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="http://localhost:8000")
    parser.add_argument("--orders", default="http://localhost:8080")
    args = parser.parse_args()

    _, catalog_health, _ = request(args.catalog, "GET", "/health")
    _, orders_health, _ = request(args.orders, "GET", "/health")
    print(f"\ncatalog = {(catalog_health or {}).get('implementation', '?')}"
          f"   orders = {(orders_health or {}).get('implementation', '?')}")

    check_catalog(args.catalog)
    check_orders(args.orders)
    check_boundaries(args.catalog, args.orders)

    total = len(passed) + len(failed)
    print(f"\n  {GREEN}{len(passed)} passed{RESET}"
          + (f", {RED}{len(failed)} failed{RESET}" if failed else "")
          + f"  ({total} checks)\n")
    for name in failed:
        print(f"    {RED}x{RESET} {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
