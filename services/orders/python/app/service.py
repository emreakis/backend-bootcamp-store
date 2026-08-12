"""One user action, three services, two protocols.

Open `monolith/python/app/orders.py` next to this file. The steps are the same three:
price the lines, charge the card, write the order. Almost every line of difference is
a consequence of those steps now crossing a network.
"""

import logging
import uuid
from datetime import datetime, timezone

from . import catalog_client, payments_client, problems, repository
from .models import Order, OrderItem, OrderLine, Payment

log = logging.getLogger("orders.service")


def checkout(items: list[OrderItem] | None, idempotency_key: str | None) -> Order:
    """NOTE WHAT IS MISSING FROM THIS FUNCTION: a transaction around the whole thing.

    That is deliberate, and it is the single most important structural decision in
    this service.

    The obvious move is to open a connection at the top and hold it to the bottom, the
    way the monolith does. Do that and you hold a database connection open across two
    network calls. A slow payments service then does not merely make checkout slow —
    it pins one connection per in-flight order until the pool is empty, at which point
    every other endpoint in this service stops working too, including the ones that
    never touch payments. You would have converted a payments outage into a total
    outage, via your connection pool.

    (The pool in `repository` is ten connections. Ten concurrent checkouts against a
    hung payments service is all it would take.)

    So: talk to the network first, hold no locks while doing it, and open a short
    local transaction only once you have everything you need to write.

    The cost is that steps 1-2 and step 3 are no longer atomic together. If this
    process dies between the charge and the insert, the customer is charged for an
    order that does not exist. That is a real hole, and the honest answers to it — an
    outbox, a reconciliation job, a saga — are the module after this bootcamp. The
    monolith closed it with one keyword. Nothing here closes it for free.
    """
    _validate(items)

    # Did we already do exactly this? A dropped response is indistinguishable from a
    # failed request, so a good client retries — and this is what makes that retry
    # safe rather than expensive.
    if idempotency_key:
        seen = repository.find_order_id_by_idempotency_key(idempotency_key)
        if seen:
            log.info("idempotency_key=%s REPLAYED -> order=%s", idempotency_key, seen)
            return get_order(seen)

    order_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).replace(microsecond=0)

    # 1. Price every line against catalog, over REST. A 404 here becomes a designed
    #    order rejection; an unreachable catalog becomes a 503.
    lines: list[OrderLine] = []
    total_cents = 0
    for item in items:
        product = catalog_client.fetch(item.sku)
        lines.append(OrderLine(sku=product.sku, name=product.name,
                               unit_cents=product.price_cents, qty=item.qty))
        total_cents += product.price_cents * item.qty

    # 2. Charge, over gRPC.
    #
    #    The idempotency key handed downstream is the ORDER ID when the client did not
    #    supply one — stable across this service's own internal retries, which is what
    #    exercise 3.2 depends on. It is deliberately NOT stable across two separate
    #    client calls with no Idempotency-Key: that is the client choosing to have no
    #    protection, and the contract says so out loud.
    downstream_key = idempotency_key or order_id
    payment_status, auth_code = payments_client.charge(order_id, total_cents, downstream_key)

    # 3. Now, and only now, a short local transaction.
    repository.persist(order_id, created_at, total_cents, lines,
                       payment_status, auth_code, idempotency_key)

    log.info("order=%s CONFIRMED total=%s lines=%s", order_id, total_cents, len(lines))
    return Order(
        id=order_id,
        status="CONFIRMED",
        total_cents=total_cents,
        created_at=created_at.isoformat().replace("+00:00", "Z"),
        lines=lines,
        payment=Payment(status=payment_status, auth_code=auth_code),
    )


def get_order(order_id: str) -> Order:
    order = repository.find_order(order_id)
    if order is None:
        raise problems.order_not_found(order_id)
    return order


def cancel(order_id: str) -> Order:
    """Cancel an order.

    Shorter than the monolith's version, because there is no stock to put back — this
    system never took any.

    What it also does not do is refund the card, and that omission is worth naming
    rather than hiding. A refund is a second call to a service that can be down, and
    doing it inline would make cancellation fail whenever payments is unwell. It
    belongs on a queue, retried until it succeeds. That is the same "after the charge,
    not in front of the customer" pattern as confirmation emails and inventory — the
    module after this bootcamp.
    """
    order = get_order(order_id)
    if order.status != "CONFIRMED":
        raise problems.order_not_cancellable(order_id, order.status)

    repository.mark_cancelled(order_id)
    log.info("order=%s CANCELLED", order_id)
    return order.model_copy(update={"status": "CANCELLED"})


def _validate(items: list[OrderItem] | None) -> None:
    if not items:
        raise problems.validation_failed("An order needs at least one item.")
    for item in items:
        if not item.sku:
            raise problems.validation_failed("Every item needs a sku.")
        if item.qty is None or item.qty < 1:
            raise problems.validation_failed("Every item needs a qty of at least 1.")
