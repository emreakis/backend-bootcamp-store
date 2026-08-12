"""The single database.

One file, one schema, every module's tables in it. `transaction()` is the thing this
whole bootcamp is about losing: an atomic scope that spans three modules, costs
nothing, and cannot half-succeed.
"""

import pathlib
import sqlite3
from contextlib import contextmanager

from . import config


def bootstrap() -> None:
    """Apply schema and seed at boot.

    Real systems use migration tools. A teaching repo uses a file you can read, and
    a database that is identical every time you start it.
    """
    if config.RESET_DB:
        for suffix in ("", "-journal", "-wal", "-shm"):
            pathlib.Path(config.DATABASE_PATH + suffix).unlink(missing_ok=True)

    schema = pathlib.Path(config.SCHEMA_PATH).read_text(encoding="utf-8")
    seed = pathlib.Path(config.SEED_PATH).read_text(encoding="utf-8")

    with connect() as conn:
        conn.executescript(schema)
        conn.executescript(seed)
        conn.commit()


@contextmanager
def connect():
    conn = sqlite3.connect(config.DATABASE_PATH, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    # Foreign keys are off by default in SQLite. Turning them on is what makes
    # order_lines.sku -> products.sku a real constraint rather than a comment.
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection):
    """One atomic scope across catalog, orders and payments.

    Look at what this buys checkout: stock is reserved, the order is written and the
    card is charged, and if the card is declined every one of those disappears. No
    compensating action, no saga, no idempotency key, no partial state to reconcile
    at 3am. One `ROLLBACK`.

    In Session 3 these three modules become three services with three databases and
    this context manager becomes impossible. Everything you will learn about sagas,
    idempotency and retries exists to buy back a fraction of what this line does for
    free.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
