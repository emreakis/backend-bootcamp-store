"""The shapes this service reads and writes.

Python's field names are already `snake_case`, which is what the contract says on the
wire — so unlike the Java implementation, nothing here needs a naming strategy. That
is a genuine convenience and also a trap: it means a typo in a field name produces a
valid-looking JSON document rather than a compiler error, which is why the pydantic
models below are declared rather than dictionaries being passed around.

They live in one file because they are data, not behaviour, and reading them together
is how you see the contract.
"""

from pydantic import BaseModel


class OrderItem(BaseModel):
    """One line of an incoming checkout request."""
    sku: str | None = None
    qty: int | None = None


class CreateOrderRequest(BaseModel):
    items: list[OrderItem] | None = None


class ProductSnapshot(BaseModel):
    """What catalog told us, at the moment we asked.

    Deliberately narrower than catalog's own product: orders has no business carrying
    a stock level around, because nothing here acts on it. Take from a dependency only
    what you use — every extra field is a thing that can change under you and a
    coupling you did not need.
    """
    sku: str
    name: str
    price_cents: int


class OrderLine(BaseModel):
    """`name` and `unit_cents` are copied from catalog at purchase time.

    Not caching, and not denormalisation for speed — correctness. An order records
    what was sold, and catalog is free to re-price tomorrow. It also happens to be
    what lets `GET /v1/orders/{id}` answer without calling anybody: a dependency you
    do not have cannot be down.
    """
    sku: str
    name: str
    unit_cents: int
    qty: int


class Payment(BaseModel):
    status: str
    auth_code: str | None = None


class Order(BaseModel):
    id: str
    status: str
    total_cents: int
    created_at: str
    lines: list[OrderLine]
    payment: Payment | None = None
