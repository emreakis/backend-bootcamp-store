# frozen_string_literal: true

# Domain outcomes, not accidents.
#
# Every class below names a thing the business decided can happen. They are raised
# deep inside a module and translated to HTTP exactly once, at the edge, in app.rb.
#
# That translation is the whole discipline: a missing product must leave this process
# as a designed 404, never as a stack trace. An API that only documents its successes
# is half designed.
class DomainError < StandardError
  attr_reader :kind, :title, :status, :detail

  def initialize(kind, title, status, detail)
    super(detail)
    @kind = kind
    @title = title
    @status = status
    @detail = detail
  end
end

class ValidationFailed < DomainError
  def initialize(detail)
    super('validation-failed', 'Validation failed', 400, detail)
  end
end

class ProductNotFound < DomainError
  def initialize(sku)
    super('product-not-found', 'Product not found', 404, "No product with sku '#{sku}'.")
  end
end

class InsufficientStock < DomainError
  def initialize(sku, requested, available)
    super('insufficient-stock', 'Insufficient stock', 409,
          "Product '#{sku}' has #{available} in stock, #{requested} requested.")
  end
end

class OrderNotFound < DomainError
  def initialize(id)
    super('order-not-found', 'Order not found', 404, "No order with id '#{id}'.")
  end
end

# A state conflict — not a bad request, and not a server bug. This is what 409 is for,
# and it is the status code most APIs forget to use.
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
