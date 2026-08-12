# frozen_string_literal: true

# Domain outcomes, not accidents.
#
# Two of these did not exist in the monolith, and their arrival is the whole story of
# this session: CatalogUnavailable and PaymentsUnavailable. In one process, a module
# could not be down while its caller was up. Now it can, and the store owes its
# customers an honest answer when it happens.
#
# Note which failures are 4xx and which are 5xx, because the split is a blame
# assignment. A declined card is 402: the caller must change something (their card), and
# retrying identically will never help. A dependency being unreachable is 503: the
# caller did nothing wrong, should not change the request, and should come back later —
# which is what retry_after tells them.
class DomainError < StandardError
  attr_reader :kind, :title, :status, :detail, :retry_after

  def initialize(kind, title, status, detail, retry_after = nil)
    super(detail)
    @kind = kind
    @title = title
    @status = status
    @detail = detail
    @retry_after = retry_after
  end
end

class ValidationFailed < DomainError
  def initialize(detail)
    super('validation-failed', 'Validation failed', 400, detail)
  end
end

# Catalog answered 404. Orders turns that into a designed order rejection rather than
# passing a dependency's status through blindly or letting it become a 500. Translating
# a dependency's vocabulary into your own is most of what an orchestrator is for.
class ProductNotFound < DomainError
  def initialize(sku)
    super('product-not-found', 'Product not found', 404, "No product with sku '#{sku}'.")
  end
end

class OrderNotFound < DomainError
  def initialize(id)
    super('order-not-found', 'Order not found', 404, "No order with id '#{id}'.")
  end
end

# A state conflict — well-formed request, healthy server, impossible transition.
class OrderNotCancellable < DomainError
  def initialize(id, status)
    super('order-not-cancellable', 'Order not cancellable', 409,
          "Order '#{id}' is #{status} and cannot be cancelled.")
  end
end

class PaymentDeclined < DomainError
  def initialize(detail)
    super('payment-declined', 'Payment declined', 402, detail)
  end
end

class CatalogUnavailable < DomainError
  def initialize(detail)
    super('catalog-unavailable', 'Catalog unavailable', 503, detail, 5)
  end
end

# The response the Session 3 exercise exists to produce.
#
# Getting a fast, honest 503 out of a payments outage is something you build. The
# default behaviour — no deadline, no breaker — is not this. It is every checkout thread
# blocking until the pool drains and the store goes down with its dependency.
class PaymentsUnavailable < DomainError
  def initialize(detail)
    super('payments-unavailable', 'Payments unavailable', 503, detail, 5)
  end
end
