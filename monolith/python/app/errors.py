"""Domain outcomes, not accidents.

Every one of these is a thing the business decided can happen. They are raised deep
inside a module and translated to HTTP exactly once, at the edge, in main.py.

That translation is the whole discipline: a missing product must leave this process
as a designed 404, never as a stack trace. An API that only documents its successes
is half designed.
"""


class DomainError(Exception):
    """Base class for every outcome the store knows how to explain."""

    problem_type: str = "about:blank"
    title: str = "Error"
    status: int = 500

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class ValidationFailed(DomainError):
    problem_type = "validation-failed"
    title = "Validation failed"
    status = 400


class ProductNotFound(DomainError):
    problem_type = "product-not-found"
    title = "Product not found"
    status = 404

    def __init__(self, sku: str):
        super().__init__(f"No product with sku '{sku}'.")
        self.sku = sku


class InsufficientStock(DomainError):
    problem_type = "insufficient-stock"
    title = "Insufficient stock"
    status = 409

    def __init__(self, sku: str, requested: int, available: int):
        super().__init__(
            f"Product '{sku}' has {available} in stock, {requested} requested."
        )


class OrderNotFound(DomainError):
    problem_type = "order-not-found"
    title = "Order not found"
    status = 404

    def __init__(self, order_id: str):
        super().__init__(f"No order with id '{order_id}'.")


class OrderNotCancellable(DomainError):
    """A state conflict — not a bad request, and not a server bug.

    This is what 409 is for, and it is the status code most APIs forget to use.
    """

    problem_type = "order-not-cancellable"
    title = "Order not cancellable"
    status = 409

    def __init__(self, order_id: str, status: str):
        super().__init__(f"Order '{order_id}' is {status} and cannot be cancelled.")


class PaymentDeclined(DomainError):
    problem_type = "payment-declined"
    title = "Payment declined"
    status = 402

    def __init__(self, detail: str):
        super().__init__(detail)
