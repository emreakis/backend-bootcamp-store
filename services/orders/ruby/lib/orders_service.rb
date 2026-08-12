# frozen_string_literal: true

require 'securerandom'
require_relative 'catalog_client'
require_relative 'errors'
require_relative 'orders_repository'
require_relative 'payments_client'

# One user action, three services, two protocols.
#
# Open `monolith/ruby/lib/orders.rb` next to this file. The steps are the same three:
# price the lines, charge the card, write the order. Almost every line of difference is
# a consequence of those steps now crossing a network.
module OrdersService
  module_function

  # NOTE WHAT IS MISSING FROM THIS METHOD: a transaction around the whole thing.
  #
  # That is deliberate, and it is the single most important structural decision in this
  # service.
  #
  # The obvious move is to wrap the lot in `connection.transaction`, the way the monolith
  # does. Do that and you hold a database connection open across two network calls. A
  # slow payments service then does not merely make checkout slow — it pins one
  # connection per in-flight order until the pool is empty, at which point every other
  # endpoint in this service stops working too, including the ones that never touch
  # payments. You would have converted a payments outage into a total outage, via your
  # connection pool.
  #
  # So: talk to the network first, hold no locks while doing it, and open a short local
  # transaction only once you have everything you need to write.
  #
  # The cost is that steps 1-2 and step 3 are no longer atomic together. If this process
  # dies between the charge and the insert, the customer is charged for an order that
  # does not exist. That is a real hole, and the honest answers to it — an outbox, a
  # reconciliation job, a saga — are the module after this bootcamp. The monolith closed
  # it with one keyword. Nothing here closes it for free.
  def checkout(items, idempotency_key)
    validate!(items)

    # Did we already do exactly this? A dropped response is indistinguishable from a
    # failed request, so a good client retries — and this is what makes that retry safe
    # rather than expensive.
    if idempotency_key && !idempotency_key.empty?
      seen = OrdersRepository.find_order_id_by_idempotency_key(idempotency_key)
      if seen
        warn "idempotency_key=#{idempotency_key} REPLAYED -> order=#{seen}"
        return get_order(seen)
      end
    end

    order_id = SecureRandom.uuid
    created_at = Time.now.utc.floor

    # 1. Price every line against catalog, over REST. A 404 here becomes a designed order
    #    rejection; an unreachable catalog becomes a 503.
    total_cents = 0
    lines = items.map do |item|
      product = CatalogClient.fetch(item['sku'])
      total_cents += product[:price_cents] * item['qty']
      { sku: product[:sku], name: product[:name],
        unit_cents: product[:price_cents], qty: item['qty'] }
    end

    # 2. Charge, over gRPC.
    #
    #    The idempotency key handed downstream is the ORDER ID when the client did not
    #    supply one — stable across this service's own internal retries, which is what
    #    exercise 3.2 depends on. It is deliberately NOT stable across two separate
    #    client calls with no Idempotency-Key: that is the client choosing to have no
    #    protection, and the contract says so out loud.
    downstream_key = idempotency_key.nil? || idempotency_key.empty? ? order_id : idempotency_key
    payment = PaymentsClient.charge(order_id, total_cents, downstream_key)

    # 3. Now, and only now, a short local transaction.
    OrdersRepository.persist(order_id, created_at, total_cents, lines, payment, idempotency_key)

    warn "order=#{order_id} CONFIRMED total=#{total_cents} lines=#{lines.size}"
    {
      id: order_id, status: 'CONFIRMED', total_cents: total_cents,
      created_at: OrdersRepository.iso(created_at), lines: lines, payment: payment
    }
  end

  def get_order(id)
    OrdersRepository.find_order(id) or raise(OrderNotFound, id)
  end

  # Cancel an order.
  #
  # Shorter than the monolith's version, because there is no stock to put back — this
  # system never took any.
  #
  # What it also does not do is refund the card, and that omission is worth naming rather
  # than hiding. A refund is a second call to a service that can be down, and doing it
  # inline would make cancellation fail whenever payments is unwell. It belongs on a
  # queue, retried until it succeeds. That is the same "after the charge, not in front of
  # the customer" pattern as confirmation emails and inventory — the module after this
  # bootcamp.
  def cancel(id)
    order = get_order(id)
    raise OrderNotCancellable.new(id, order[:status]) unless order[:status] == 'CONFIRMED'

    OrdersRepository.mark_cancelled(id)
    warn "order=#{id} CANCELLED"
    order.merge(status: 'CANCELLED')
  end

  def validate!(items)
    raise ValidationFailed, 'An order needs at least one item.' unless items.is_a?(Array) && !items.empty?

    items.each do |item|
      unless item.is_a?(Hash) && item['sku'].is_a?(String) && !item['sku'].empty?
        raise ValidationFailed, 'Every item needs a sku.'
      end
      unless item['qty'].is_a?(Integer) && item['qty'] >= 1
        raise ValidationFailed, 'Every item needs a qty of at least 1.'
      end
    end
  end
end
