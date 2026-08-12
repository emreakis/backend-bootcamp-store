"""MODULE: catalog — owns `products`.

Public API: list_products, get_product, reserve, release.

No other module may touch the `products` table. If `orders` wants a price, it calls
`get_product`; if it wants stock, it calls `reserve`. That restriction is the only
thing standing between this monolith and a big ball of mud, and it is what makes the
Session 3 split a mechanical exercise rather than a rewrite.
"""

import sqlite3
from dataclasses import dataclass

from .errors import InsufficientStock, ProductNotFound


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price_cents: int
    stock: int


def _row_to_product(row: sqlite3.Row) -> Product:
    return Product(row["sku"], row["name"], row["price_cents"], row["stock"])


def list_products(
    conn: sqlite3.Connection, limit: int = 20, cursor: str | None = None
) -> tuple[list[Product], str | None]:
    """One page of products, newest cursor last.

    Keyset pagination, not OFFSET. An offset drifts: insert a product while a client
    is on page 2 and it either sees a row twice or misses one entirely. A cursor is
    a position in the data, not a count of rows someone else can change.

    We ask for limit + 1 rows: if the extra one comes back there is another page.
    """
    if cursor:
        rows = conn.execute(
            "SELECT * FROM products WHERE sku > ? ORDER BY sku LIMIT ?",
            (cursor, limit + 1),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM products ORDER BY sku LIMIT ?", (limit + 1,)
        ).fetchall()

    has_more = len(rows) > limit
    page = [_row_to_product(r) for r in rows[:limit]]
    return page, (page[-1].sku if has_more and page else None)


def get_product(conn: sqlite3.Connection, sku: str) -> Product:
    row = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
    if row is None:
        raise ProductNotFound(sku)
    return _row_to_product(row)


def reserve(conn: sqlite3.Connection, sku: str, qty: int) -> Product:
    """Take `qty` units off the shelf and return the product as it was priced.

    Note the shape of this call: the caller passes in *its* connection, so this runs
    inside the caller's transaction. Reserving stock and writing the order are one
    atomic act, and neither module had to know that.

    Once catalog is a separate service this parameter is the first thing to go — and
    with it, atomicity. What replaces it is a saga, and a compensating "un-reserve"
    that has to survive the process crashing between the two calls.
    """
    product = get_product(conn, sku)
    if product.stock < qty:
        raise InsufficientStock(sku, qty, product.stock)

    conn.execute(
        "UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?",
        (qty, sku, qty),
    )
    return product


def release(conn: sqlite3.Connection, sku: str, qty: int) -> None:
    """Put stock back — used when an order is cancelled."""
    conn.execute("UPDATE products SET stock = stock + ? WHERE sku = ?", (qty, sku))
