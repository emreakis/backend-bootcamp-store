"""MODULE: orders — owns `orders` and `order_lines`.

Public API: checkout, get_order, cancel.

The orchestrator, and the only module that depends on the other two. Trace the call
chain in `checkout` — it is the same chain Session 3 draws across three services,
except that here every arrow is a function call that cannot fail on its own.
"""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from . import catalog, payments
from .db import transaction
from .errors import OrderNotCancellable, OrderNotFound, ValidationFailed


@dataclass(frozen=True)
class OrderLine:
    sku: str
    name: str
    unit_cents: int
    qty: int


@dataclass(frozen=True)
class Order:
    id: str
    status: str
    total_cents: int
    created_at: str
    lines: list[OrderLine]
    payment: payments.Payment | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def checkout(conn: sqlite3.Connection, items: list[dict]) -> Order:
    """One user action, three modules, one transaction.

    Read this next to the Session 3 diagram of the same flow. The steps are
    identical. The difference is that every step here either happens or does not
    happen, together, and there is no state in between for anyone to observe.
    """
    if not items:
        raise ValidationFailed("An order needs at least one item.")
    for item in items:
        if not item.get("sku"):
            raise ValidationFailed("Every item needs a sku.")
        if not isinstance(item.get("qty"), int) or item["qty"] < 1:
            raise ValidationFailed("Every item needs a qty of at least 1.")

    order_id = str(uuid.uuid4())
    created_at = _now()

    with transaction(conn):
        # 1. Reserve stock and capture the price AS IT IS NOW. Calling into catalog,
        #    never touching its table.
        lines: list[OrderLine] = []
        for item in items:
            product = catalog.reserve(conn, item["sku"], item["qty"])
            lines.append(
                OrderLine(product.sku, product.name, product.price_cents, item["qty"])
            )

        total_cents = sum(line.unit_cents * line.qty for line in lines)

        # 2. Write the order. The line rows copy name and unit_cents on purpose: an
        #    order records what was sold, not what the catalog says next week.
        conn.execute(
            "INSERT INTO orders (id, status, total_cents, created_at) VALUES (?, ?, ?, ?)",
            (order_id, "CONFIRMED", total_cents, created_at),
        )
        conn.executemany(
            "INSERT INTO order_lines (order_id, sku, name, unit_cents, qty)"
            " VALUES (?, ?, ?, ?, ?)",
            [(order_id, ln.sku, ln.name, ln.unit_cents, ln.qty) for ln in lines],
        )

        # 3. Charge. A decline raises, the transaction rolls back, and the stock
        #    reserved in step 1 is back on the shelf without anyone writing code to
        #    put it there. That last clause is what Session 3 costs you.
        payment = payments.charge(conn, order_id, total_cents)

    return Order(order_id, "CONFIRMED", total_cents, created_at, lines, payment)


def get_order(conn: sqlite3.Connection, order_id: str) -> Order:
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        raise OrderNotFound(order_id)

    line_rows = conn.execute(
        "SELECT * FROM order_lines WHERE order_id = ? ORDER BY sku", (order_id,)
    ).fetchall()

    return Order(
        id=row["id"],
        status=row["status"],
        total_cents=row["total_cents"],
        created_at=row["created_at"],
        lines=[
            OrderLine(r["sku"], r["name"], r["unit_cents"], r["qty"]) for r in line_rows
        ],
        # Again: through the module's API, not its table.
        payment=payments.find_for_order(conn, order_id),
    )


def cancel(conn: sqlite3.Connection, order_id: str) -> Order:
    """Cancel an order and put its stock back.

    Cancelling an already-cancelled order is a 409, not a 400 and not a 500. The
    request was well formed and the server is healthy; the resource is simply not in
    a state where this makes sense.
    """
    order = get_order(conn, order_id)
    if order.status != "CONFIRMED":
        raise OrderNotCancellable(order_id, order.status)

    with transaction(conn):
        for line in order.lines:
            catalog.release(conn, line.sku, line.qty)
        conn.execute(
            "UPDATE orders SET status = ? WHERE id = ?", ("CANCELLED", order_id)
        )

    return Order(
        order.id, "CANCELLED", order.total_cents, order.created_at, order.lines, order.payment
    )
