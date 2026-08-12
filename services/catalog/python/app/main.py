"""CATALOG — the read side of the store, and the simplest service in the system.

Small enough to read in full, which is why it is the one to read first. Everything
here satisfies contracts/catalog.v1.yaml; if this file and that file disagree, this
file is wrong.

Compare it with `monolith/python/app/catalog.py`. The SQL is identical. What changed
is everything around it: its own database, its own process, its own deployment, and a
`reserve` function that no longer exists because stock cannot be taken off a shelf in
one database inside a transaction that lives in another.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from . import config

PROBLEM_BASE = "https://bootcamp.backendguru.io/problems/"

pool: ConnectionPool


class Product(BaseModel):
    sku: str
    name: str
    price_cents: int
    stock: int


class ProductPage(BaseModel):
    items: list[Product]
    next_cursor: str | None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global pool
    # The pool waits for the database rather than crashing if it is a second behind.
    # compose already gates startup on a healthcheck; this is the belt to that braces,
    # because in a real platform nothing promises your dependencies start first.
    pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=10, open=True)
    pool.wait(timeout=30.0)
    yield
    pool.close()


app = FastAPI(title="Catalog", version="1.0.0", lifespan=lifespan)


def problem(status: int, kind: str, title: str, detail: str, instance: str):
    """One error envelope, everywhere. RFC 9457, exactly as contracts/problem.yaml says."""
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": PROBLEM_BASE + kind,
            "title": title,
            "status": status,
            "detail": detail,
            "instance": instance,
        },
    )


@app.get("/health")
def health():
    """Liveness only — it does not touch the database.

    Tempting to run `SELECT 1` here. Don't. If this endpoint failed whenever Postgres
    hiccupped, the platform would start killing catalog pods during a database blip,
    removing capacity exactly when the system is least able to spare it.
    """
    return {"status": "ok", "implementation": config.IMPLEMENTATION}


@app.get("/v1/products", response_model=ProductPage)
def list_products(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
):
    """Keyset pagination. An offset would drift under concurrent inserts; a cursor
    is a position in the data rather than a count of rows someone else can change.

    Ask for limit + 1 rows: if the extra one comes back, there is another page.
    """
    with pool.connection() as conn:
        if cursor:
            rows = conn.execute(
                "SELECT sku, name, price_cents, stock FROM products"
                " WHERE sku > %s ORDER BY sku LIMIT %s",
                (cursor, limit + 1),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT sku, name, price_cents, stock FROM products ORDER BY sku LIMIT %s",
                (limit + 1,),
            ).fetchall()

    has_more = len(rows) > limit
    items = [Product(sku=r[0], name=r[1], price_cents=r[2], stock=r[3]) for r in rows[:limit]]
    return ProductPage(items=items, next_cursor=items[-1].sku if has_more and items else None)


@app.get("/v1/products/{sku}", response_model=Product)
def get_product(sku: str, request: Request):
    """The call `orders` makes during checkout.

    Its 404 is the most consequential response in this service. Orders has to turn it
    into a designed order rejection — so it must be unambiguous, carry the sku that
    was missing, and never arrive as a 500. A dependency that fails clearly is a
    dependency you can build on.
    """
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT sku, name, price_cents, stock FROM products WHERE sku = %s", (sku,)
        ).fetchone()

    if row is None:
        return problem(404, "product-not-found", "Product not found",
                       f"No product with sku '{sku}'.", request.url.path)

    return Product(sku=row[0], name=row[1], price_cents=row[2], stock=row[3])


@app.exception_handler(RequestValidationError)
async def invalid_query(request: Request, exc: RequestValidationError):
    """`limit` outside 1..100, or not a number at all.

    FastAPI's default here is a 422 carrying pydantic's own error structure — two
    things the contract does not have. A framework's default is a framework's opinion;
    contracts/catalog.v1.yaml is the agreement, and it says 400 in this envelope.

    Worth knowing that this is the single most common way an implementation drifts
    from its spec: not by getting an endpoint wrong, but by letting the framework
    answer for it on a path nobody wrote by hand. The conformance suite checks it for
    exactly that reason.
    """
    return problem(400, "validation-failed", "Validation failed",
                   "limit must be an integer between 1 and 100.", request.url.path)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    """Anything unnamed is a bug. 500, and the detail stays in our logs — never in a
    response body where it becomes a client's problem to parse and an attacker's to read.
    """
    return problem(500, "internal-error", "Internal server error",
                   "The request could not be completed.", request.url.path)
