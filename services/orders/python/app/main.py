"""ORDERS — the orchestrator.

REST at the edge, gRPC inside, two databases it cannot join across, and the only
service in this system that can be woken up by somebody else's outage.

Everything here satisfies contracts/orders.v1.yaml; if this file and that file
disagree, this file is wrong.

The endpoints below are `def`, not `async def`, on purpose. FastAPI runs a plain `def`
in a worker thread, which is what makes the blocking psycopg and blocking gRPC calls
inside legal. Declare one of these `async` without making everything underneath it
async too and a single slow charge blocks the event loop for every other request in
the process — the same "one dependency takes the whole service down" failure this
session is about, arriving through a different door.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError

from . import config, problems, repository, service
from .models import CreateOrderRequest, Order

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    repository.open_pool()
    yield
    repository.close_pool()


app = FastAPI(title="Orders", version="1.0.0", lifespan=lifespan)


@app.exception_handler(problems.DomainError)
async def on_domain_error(request: Request, exc: problems.DomainError):
    """One error envelope, everywhere — RFC 9457, exactly as contracts/problem.yaml says."""
    return problems.problem_response(exc.status, exc.kind, exc.title, exc.detail,
                                     request.url.path, exc.retry_after_seconds)


@app.exception_handler(404)
async def on_no_route(request: Request, _exc):
    """A path that matches no route, including `GET /v1/orders/{not-a-uuid}` handled
    below. Rendered as a problem document rather than FastAPI's bare `{"detail": ...}`
    so that every error out of this service has the same shape.
    """
    return problems.problem_response(404, "order-not-found", "Order not found",
                                     f"No order with id '{request.url.path}'.",
                                     request.url.path)


@app.exception_handler(Exception)
async def on_unexpected(request: Request, exc: Exception):
    """Anything unnamed is a bug. 500, and the detail stays in our logs — never in a
    response body where it becomes a client's problem to parse and an attacker's to read.
    """
    logging.getLogger("orders").exception("unhandled error on %s", request.url.path)
    return problems.problem_response(500, "internal-error", "Internal server error",
                                     "The request could not be completed.",
                                     request.url.path)


@app.get("/health")
def health():
    """Liveness only, and here that matters more than anywhere else in the system.

    Orders has dependencies, so the temptation to check them is real. Give in to it
    and a payments outage makes orders report unhealthy, and the platform starts
    restarting orders pods — removing capacity from a service that was working, during
    an incident, because we told it to.

    Orders is not sick when payments is down. It is degraded. That distinction belongs
    in metrics and alerts, not in the endpoint an orchestrator uses to decide whether
    to kill you.
    """
    return {"status": "ok", "implementation": config.IMPLEMENTATION}


@app.post("/v1/orders", response_model=Order, status_code=201)
def create_order(body: CreateOrderRequest, response: Response,
                 idempotency_key: str | None = Header(default=None,
                                                      alias="Idempotency-Key")):
    order = service.checkout(body.items if body else None, idempotency_key)
    response.headers["Location"] = f"/v1/orders/{order.id}"
    return order


@app.get("/v1/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    return service.get_order(order_id)


@app.post("/v1/orders/{order_id}/cancel", response_model=Order)
def cancel_order(order_id: str):
    return service.cancel(order_id)


@app.exception_handler(RequestValidationError)
async def on_unprocessable(request: Request, _exc: RequestValidationError):
    """pydantic rejected the body before our own validation ran.

    Mapped to 400 rather than FastAPI's default 422, because the contract has no 422:
    a malformed body is a malformed body, and having two statuses for it means every
    client has to handle both. The framework's default is a framework's opinion; the
    contract is the agreement.
    """
    return problems.problem_response(400, "validation-failed", "Validation failed",
                                     "Body must be a JSON object with an `items` array.",
                                     request.url.path)
