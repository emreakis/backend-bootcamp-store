"""The HTTP layer. The only place in the process that knows what a status code is.

Everything above this file is domain logic that would be identical in a desktop app.
That separation is not decoration: in Session 3, `catalog` and `payments` grow their
own HTTP and gRPC edges, and the module code underneath them barely changes.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import catalog, config, db, orders
from .errors import DomainError

PROBLEM_BASE = "https://bootcamp.backendguru.io/problems/"


# --- the contract, as models -------------------------------------------------
# The model is the contract: it validates the request, serialises the response and
# generates the OpenAPI document at /openapi.json — all from one declaration. Open
# http://localhost:8080/docs and note that you already have a machine-readable
# contract you did not write. Session 2 is about writing one on purpose.


class ProductOut(BaseModel):
    sku: str
    name: str
    price_cents: int
    stock: int


class ProductPage(BaseModel):
    items: list[ProductOut]
    next_cursor: str | None


class OrderItemIn(BaseModel):
    sku: str = Field(min_length=1)
    qty: int = Field(ge=1)


class OrderIn(BaseModel):
    items: list[OrderItemIn] = Field(min_length=1)


class OrderLineOut(BaseModel):
    sku: str
    name: str
    unit_cents: int
    qty: int


class PaymentOut(BaseModel):
    status: str
    auth_code: str | None


class OrderOut(BaseModel):
    id: str
    status: str
    total_cents: int
    created_at: str
    lines: list[OrderLineOut]
    payment: PaymentOut | None


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.bootstrap()
    yield


app = FastAPI(
    title="The Store (modular monolith)",
    version="1.0.0",
    lifespan=lifespan,
)


# --- errors ------------------------------------------------------------------


def _problem(status: int, type_suffix: str, title: str, detail: str, instance: str):
    """One error envelope, everywhere. RFC 9457 Problem Details.

    A client that learns this shape once handles every failure this API can produce.
    Bespoke error bodies per endpoint are how you make consumers write a parser per
    endpoint.
    """
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": PROBLEM_BASE + type_suffix,
            "title": title,
            "status": status,
            "detail": detail,
            "instance": instance,
        },
    )


@app.exception_handler(DomainError)
async def handle_domain_error(request: Request, exc: DomainError):
    """Domain outcome in, HTTP out. Translated once, at the edge."""
    return _problem(
        exc.status, exc.problem_type, exc.title, exc.detail, request.url.path
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    """FastAPI's default is 422 with its own body shape. We owe callers our envelope."""
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(p) for p in first.get("loc", ())[1:]) or "body"
    return _problem(
        400,
        "validation-failed",
        "Validation failed",
        f"{location}: {first.get('msg', 'invalid request')}",
        request.url.path,
    )


# --- endpoints ---------------------------------------------------------------


@app.get("/health")
def health():
    """Liveness only — deliberately checks nothing downstream.

    Session 3 revisits this. A health check that calls its dependencies turns one
    service's outage into everyone's outage, because the platform starts killing
    healthy pods for being downstream of a sick one.
    """
    return {"status": "ok", "implementation": config.IMPLEMENTATION}


@app.get("/v1/products", response_model=ProductPage)
def list_products(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
):
    with db.connect() as conn:
        items, next_cursor = catalog.list_products(conn, limit, cursor)
    return ProductPage(items=[ProductOut(**vars(p)) for p in items], next_cursor=next_cursor)


@app.get("/v1/products/{sku}", response_model=ProductOut)
def get_product(sku: str):
    with db.connect() as conn:
        return ProductOut(**vars(catalog.get_product(conn, sku)))


@app.post("/v1/orders", response_model=OrderOut, status_code=201)
def create_order(body: OrderIn, response: Response):
    with db.connect() as conn:
        order = orders.checkout(conn, [item.model_dump() for item in body.items])
    response.headers["Location"] = f"/v1/orders/{order.id}"
    return _order_out(order)


@app.get("/v1/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: str):
    with db.connect() as conn:
        return _order_out(orders.get_order(conn, order_id))


@app.post("/v1/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(order_id: str):
    with db.connect() as conn:
        return _order_out(orders.cancel(conn, order_id))


def _order_out(order: orders.Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        status=order.status,
        total_cents=order.total_cents,
        created_at=order.created_at,
        lines=[OrderLineOut(**vars(line)) for line in order.lines],
        payment=(
            PaymentOut(status=order.payment.status, auth_code=order.payment.auth_code)
            if order.payment
            else None
        ),
    )
