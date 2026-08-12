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
# EXERCISE 3.4 — the timeout.
#
# httpx.Timeout takes separate connect/read/write/pool values, and the split is the
# useful part: `connect` is "I cannot reach this host", `read` is "this host accepted
# my connection and then went quiet". Different failures, different causes, and only
# the second one is what `docker compose pause catalog` produces.
#
# A single float sets all four, which is enough for a teaching system. In a real
# service they usually differ: connect is fast and unforgiving, read is generous enough
# for the slowest legitimate response.
#
# Note what this replaced: `timeout=None`, not httpx's 5-second default. That default
# was switched off on `main` on purpose, because five seconds is httpx's opinion about
# a reasonable wait and CATALOG_TIMEOUT_MS is *your* statement about how long a
# checkout may spend pricing a line. They happen to share units. They are not the same
# number, and inheriting one when you meant the other is how a service ends up with a
# latency budget nobody chose.
#
# Prove it: `docker compose pause catalog` and post an order. Before this change the
# request hung; now it is a 503 in one second.
# ============================================================================
_http = httpx.Client(
    base_url=config.CATALOG_URL,
    timeout=httpx.Timeout(config.CATALOG_TIMEOUT_MS / 1000.0),
)


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
