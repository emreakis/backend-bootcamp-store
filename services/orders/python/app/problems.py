"""Domain outcomes, not accidents — plus the one error envelope they all render into.

Two of these did not exist in the monolith, and their arrival is the whole story of
this session: `catalog_unavailable` and `payments_unavailable`. In one process, a
module could not be down while its caller was up. Now it can, and the store owes its
customers an honest answer when it happens.

Note which failures are 4xx and which are 5xx, because the split is a blame assignment.
A declined card is 402: the caller must change something (their card), and retrying
identically will never help. A dependency being unreachable is 503: the caller did
nothing wrong, should not change the request, and should come back later — which is
what `retry_after_seconds` tells them.
"""

from fastapi.responses import JSONResponse

PROBLEM_BASE = "https://bootcamp.backendguru.io/problems/"


class DomainError(Exception):
    """A failure this service designed, as opposed to one that happened to it."""

    def __init__(self, kind: str, title: str, status: int, detail: str,
                 retry_after_seconds: int | None = None):
        super().__init__(detail)
        self.kind = kind
        self.title = title
        self.status = status
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds


def validation_failed(detail: str) -> DomainError:
    return DomainError("validation-failed", "Validation failed", 400, detail)


def product_not_found(sku: str) -> DomainError:
    """Catalog answered 404.

    Orders turns that into a designed order rejection rather than passing a
    dependency's status through blindly or letting it become a 500. Translating a
    dependency's vocabulary into your own is most of what an orchestrator is for.
    """
    return DomainError("product-not-found", "Product not found", 404,
                       f"No product with sku '{sku}'.")


def order_not_found(order_id: str) -> DomainError:
    return DomainError("order-not-found", "Order not found", 404,
                       f"No order with id '{order_id}'.")


def order_not_cancellable(order_id: str, status: str) -> DomainError:
    """A state conflict — well-formed request, healthy server, impossible transition."""
    return DomainError("order-not-cancellable", "Order not cancellable", 409,
                       f"Order '{order_id}' is {status} and cannot be cancelled.")


def payment_declined(detail: str) -> DomainError:
    return DomainError("payment-declined", "Payment declined", 402, detail)


def catalog_unavailable(detail: str) -> DomainError:
    return DomainError("catalog-unavailable", "Catalog unavailable", 503, detail, 5)


def payments_unavailable(detail: str) -> DomainError:
    """The response the Session 3 exercise exists to produce.

    Getting a fast, honest 503 out of a payments outage is something you build. The
    default behaviour — no deadline, no breaker — is not this. It is every checkout
    thread blocking until the pool drains and the store goes down with its dependency.
    """
    return DomainError("payments-unavailable", "Payments unavailable", 503, detail, 5)


def problem_response(status: int, kind: str, title: str, detail: str, instance: str,
                     retry_after_seconds: int | None = None) -> JSONResponse:
    """One error envelope, everywhere — RFC 9457, exactly as contracts/problem.yaml says."""
    headers = {}
    if retry_after_seconds is not None:
        # Tells a well-behaved client when to come back, so it backs off instead of
        # joining the stampede that is currently keeping the dependency down.
        headers["Retry-After"] = str(retry_after_seconds)

    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        headers=headers,
        content={
            "type": PROBLEM_BASE + kind,
            "title": title,
            "status": status,
            "detail": detail,
            "instance": instance,
        },
    )
