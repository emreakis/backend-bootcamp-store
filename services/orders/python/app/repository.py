"""Everything this service knows how to persist — and it is only ever its own tables.

There is no `products` table here to join to. Catalog's data lives in a different
database, in a different container, behind a different set of credentials, and no
query in this file could reach it if it wanted to.
"""

import uuid
from datetime import datetime

from psycopg_pool import ConnectionPool

from . import config
from .models import Order, OrderLine, Payment

pool: ConnectionPool | None = None


def open_pool() -> None:
    """Open the pool at startup and wait for the database rather than crashing if it
    is a second behind. compose already gates startup on a healthcheck; this is the
    belt to that braces, because in a real platform nothing promises your dependencies
    start first.
    """
    global pool
    pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=10, open=True)
    pool.wait(timeout=30.0)


def close_pool() -> None:
    if pool is not None:
        pool.close()


def _iso(moment: datetime) -> str:
    """RFC 3339, UTC, seconds precision — what the contract says."""
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def find_order_id_by_idempotency_key(key: str) -> str | None:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT order_id FROM idempotency_keys WHERE key = %s", (key,)
        ).fetchone()
    return str(row[0]) if row else None


def persist(order_id: str, created_at: datetime, total_cents: int,
            lines: list[OrderLine], payment_status: str, auth_code: str,
            idempotency_key: str | None) -> None:
    """The whole write, in one short local transaction.

    This is what is left of the monolith's checkout transaction. It still spans the
    order, its lines and the payment outcome, because those all live here — but it no
    longer spans catalog's stock, because catalog's stock is in another database and
    no transaction manager on earth will help you.

    Note how little time it is open for. Both network calls already happened, outside.
    See the comment in `service.checkout`.
    """
    order_uuid = uuid.UUID(order_id)

    # psycopg opens a transaction on the first statement and commits when this block
    # exits cleanly — so the three writes below are one unit, and a failure rolls the
    # lot back.
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO orders (id, status, total_cents, created_at, payment_status,"
            " payment_auth_code) VALUES (%s, %s, %s, %s, %s, %s)",
            (order_uuid, "CONFIRMED", total_cents, created_at, payment_status, auth_code),
        )

        for line in lines:
            conn.execute(
                "INSERT INTO order_lines (order_id, sku, name, unit_cents, qty)"
                " VALUES (%s, %s, %s, %s, %s)",
                (order_uuid, line.sku, line.name, line.unit_cents, line.qty),
            )

        # Written in the SAME transaction as the order. If it were a second, separate
        # write, a crash between the two would leave an order whose idempotency key
        # was never recorded — and the client's retry would cheerfully create a
        # duplicate. Atomicity is still available here; it is only cross-service
        # atomicity that is gone.
        if idempotency_key:
            conn.execute(
                "INSERT INTO idempotency_keys (key, order_id, created_at)"
                " VALUES (%s, %s, %s)",
                (idempotency_key, order_uuid, created_at),
            )


def find_order(order_id: str) -> Order | None:
    try:
        order_uuid = uuid.UUID(order_id)
    except ValueError:
        # Not a uuid at all, so it cannot name an order. A 404 rather than a 500 or a
        # database error leaking out through the driver.
        return None

    with pool.connection() as conn:
        header = conn.execute(
            "SELECT id, status, total_cents, created_at, payment_status,"
            " payment_auth_code FROM orders WHERE id = %s",
            (order_uuid,),
        ).fetchone()

        if header is None:
            return None

        rows = conn.execute(
            "SELECT sku, name, unit_cents, qty FROM order_lines WHERE order_id = %s"
            " ORDER BY sku",
            (order_uuid,),
        ).fetchall()

    return Order(
        id=str(header[0]),
        status=header[1],
        total_cents=header[2],
        created_at=_iso(header[3]),
        lines=[OrderLine(sku=r[0], name=r[1], unit_cents=r[2], qty=r[3]) for r in rows],
        payment=Payment(status=header[4], auth_code=header[5]) if header[4] else None,
    )


def mark_cancelled(order_id: str) -> None:
    with pool.connection() as conn:
        conn.execute("UPDATE orders SET status = %s WHERE id = %s",
                     ("CANCELLED", uuid.UUID(order_id)))
