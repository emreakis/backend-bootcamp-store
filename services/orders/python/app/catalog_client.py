"""The REST half of this service's dependencies.

In the monolith this was `catalog.get_product(conn, sku)` — a function call that could
not fail on its own. It is now an HTTP request over a network, and every one of the
eight fallacies applies to it.
"""

import logging

import httpx

from . import config, problems
from .models import ProductSnapshot

log = logging.getLogger("orders.catalog")

# ============================================================================
# TODO (exercise 3.4) — GIVE THIS CLIENT A TIMEOUT.
#
# Read the `timeout=None` below carefully, because Python is the odd one out here.
#
# httpx is one of very few HTTP clients that ships a sensible default — 5 seconds,
# connect and read. It has been switched OFF on purpose, and for two reasons.
#
#   1. So this exercise matches the other five languages. Java's RestClient, Go's
#      bare http.Client, Node's fetch and Ruby's Net::HTTP all wait forever out of
#      the box. `requests`, the library most Python developers actually reach for,
#      also defaults to None. httpx is the exception, not the rule.
#
#   2. Because a library default is not a policy. Five seconds is httpx's opinion
#      about a reasonable wait; CATALOG_TIMEOUT_MS is *your* statement about how
#      long a checkout may spend pricing a line. Those are different numbers that
#      happen to share units, and inheriting one when you meant the other is how a
#      service ends up with a timeout budget nobody chose.
#
# So: build the client with an explicit timeout from config.CATALOG_TIMEOUT_MS.
# httpx.Timeout takes separate connect/read/write/pool values; a single float sets
# them all, which is fine here.
#
#     timeout=httpx.Timeout(config.CATALOG_TIMEOUT_MS / 1000)
#
# Then prove it: `docker compose pause catalog` and post an order. Before the fix the
# request hangs; after it, you get a 503 in one second. `pause` rather than `stop`,
# because a stopped container refuses connections instantly and a paused one leaves
# you hanging — which is the whole point.
# ============================================================================
_http = httpx.Client(base_url=config.CATALOG_URL, timeout=None)


def fetch(sku: str) -> ProductSnapshot:
    """Price one sku.

    Three outcomes, and all three are designed:

      * the product exists — we take its name and price and stop caring about it;
      * catalog says 404 — a *designed order rejection*, not a 500. Passing a
        dependency's status straight through would be lazy; letting it become a stack
        trace would be worse;
      * catalog cannot be reached — 503, because the customer did nothing wrong.
    """
    try:
        response = _http.get(f"/v1/products/{sku}")
    except httpx.TimeoutException:
        # Only reachable once exercise 3.4 is done. Until then this client is patient
        # to a fault and the request simply never comes back.
        log.warning("catalog timed out for sku=%s", sku)
        raise problems.catalog_unavailable(
            "The catalog service did not respond in time. No order was placed.")
    except httpx.HTTPError as unreachable:
        # Connection refused, DNS failure, connection reset.
        log.warning("catalog unreachable for sku=%s: %s", sku, unreachable)
        raise problems.catalog_unavailable(
            "The catalog service could not be reached. No order was placed.")

    if response.status_code == 404:
        raise problems.product_not_found(sku)

    if response.status_code != 200:
        log.warning("catalog answered %s for sku=%s", response.status_code, sku)
        raise problems.catalog_unavailable(
            "The catalog service returned an unusable response. No order was placed.")

    body = response.json()
    return ProductSnapshot(sku=body["sku"], name=body["name"],
                           price_cents=body["price_cents"])
