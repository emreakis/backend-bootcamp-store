"""MODULE: payments — owns `payments`.

Public API: charge, find_for_order.

Stands in for a real card provider. In Session 3 this module becomes a gRPC service
and this function becomes a network call with a deadline, a retry policy and a
circuit breaker in front of it. Today it is a function call: it cannot time out, it
cannot be down, and it cannot answer twice.
"""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config
from .errors import PaymentDeclined


@dataclass(frozen=True)
class Payment:
    id: str
    order_id: str
    amount_cents: int
    status: str
    auth_code: str | None


def find_for_order(conn: sqlite3.Connection, order_id: str) -> Payment | None:
    """The payment recorded against an order, if there is one.

    `orders` needs this to render an order, and `orders` may not read the `payments`
    table — so the need becomes a function on this module's public API. That is the
    rule doing its job: every cross-module need surfaces as a call, and every call is
    a candidate to become a network hop on Saturday.
    """
    row = conn.execute(
        "SELECT * FROM payments WHERE order_id = ? ORDER BY created_at DESC LIMIT 1",
        (order_id,),
    ).fetchone()
    if row is None:
        return None
    return Payment(
        row["id"], row["order_id"], row["amount_cents"], row["status"], row["auth_code"]
    )


def charge(conn: sqlite3.Connection, order_id: str, amount_cents: int) -> Payment:
    """Charge the card, record the attempt, return the authorisation.

    Declines are recorded too. An audit trail with only the successes in it is not an
    audit trail — and when this becomes a remote service, "did the charge happen?" is
    a question you will need the database to answer.
    """
    declined = (
        config.PAYMENT_ALWAYS_DECLINE or amount_cents > config.PAYMENT_DECLINE_OVER_CENTS
    )

    payment = Payment(
        id=str(uuid.uuid4()),
        order_id=order_id,
        amount_cents=amount_cents,
        status="DECLINED" if declined else "APPROVED",
        auth_code=None if declined else f"AUTH-{uuid.uuid4().hex[:8].upper()}",
    )

    conn.execute(
        "INSERT INTO payments (id, order_id, amount_cents, status, auth_code, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            payment.id,
            payment.order_id,
            payment.amount_cents,
            payment.status,
            payment.auth_code,
            datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        ),
    )

    if declined:
        # Raising here rolls back the caller's transaction — including this INSERT.
        # That is the honest trade: we lose the record of the decline, but we cannot
        # possibly leave a confirmed order behind an unpaid card. Session 3 has to
        # choose between those two outcomes explicitly, because it can no longer have
        # both.
        raise PaymentDeclined(
            f"Card declined for {amount_cents} cents "
            f"(limit {config.PAYMENT_DECLINE_OVER_CENTS})."
        )

    return payment
