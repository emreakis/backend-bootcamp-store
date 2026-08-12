# frozen_string_literal: true

require 'securerandom'
require_relative 'catalog'
require_relative 'database'
require_relative 'errors'
require_relative 'payments'

# MODULE: orders — owns `orders` and `order_lines`.
#
# Public API: checkout, get_order, cancel.
#
# The orchestrator, and the only module that depends on the other two. Trace the call
# chain in `checkout` — it is the same chain Session 3 draws across three services,
# except that here every arrow is a method call that cannot fail on its own.
module Orders
  module_function

  # One user action, three modules, one transaction.
  #
  # Read this next to the Session 3 diagram of the same flow. The steps are identical.
  # The difference is that every step here either happens or does not happen, together,
  # and there is no state in between for anyone to observe.
  def checkout(items)
    raise ValidationFailed, 'An order needs at least one item.' if !items.is_a?(Array) || items.empty?

    items.each do |item|
      raise ValidationFailed, 'Every item needs a sku.' unless item.is_a?(Hash) && item['sku']
      raise ValidationFailed, 'Every item needs a qty of at least 1.' unless item['qty'].is_a?(Integer) && item['qty'] >= 1
    end

    id = SecureRandom.uuid
    created_at = Time.now.utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    Database.transaction do
      # 1. Reserve stock and capture the price AS IT IS NOW. Calling into catalog,
      #    never touching its table.
      lines = items.map do |item|
        product = Catalog.reserve(item['sku'], item['qty'])
        { sku: product[:sku], name: product[:name],
          unit_cents: product[:price_cents], qty: item['qty'] }
      end

      total_cents = lines.sum { |line| line[:unit_cents] * line[:qty] }

      # 2. Write the order. The line rows copy name and unit_cents on purpose: an order
      #    records what was sold, not what the catalog says next week.
      Database.execute('INSERT INTO orders (id, status, total_cents, created_at)' \
                       ' VALUES (?, ?, ?, ?)', id, 'CONFIRMED', total_cents, created_at)
      lines.each do |line|
        Database.execute('INSERT INTO order_lines (order_id, sku, name, unit_cents, qty)' \
                         ' VALUES (?, ?, ?, ?, ?)',
                         id, line[:sku], line[:name], line[:unit_cents], line[:qty])
      end

      # 3. Charge. A decline raises, the transaction rolls back, and the stock reserved
      #    in step 1 is back on the shelf without anyone writing code to put it there.
      #    That last clause is what Session 3 costs you.
      payment = Payments.charge(id, total_cents)

      { id: id, status: 'CONFIRMED', total_cents: total_cents, created_at: created_at,
        lines: lines,
        payment: { status: payment[:status], auth_code: payment[:auth_code] } }
    end
  end

  def get_order(id)
    row = Database.query('SELECT id, status, total_cents, created_at FROM orders WHERE id = ?',
                         id).first
    raise OrderNotFound, id if row.nil?

    lines = Database.query('SELECT sku, name, unit_cents, qty FROM order_lines' \
                           ' WHERE order_id = ? ORDER BY sku', id).map do |line|
      { sku: line[0], name: line[1], unit_cents: line[2], qty: line[3] }
    end

    # Again: through the module's API, not its table.
    payment = Payments.find_for_order(id)

    { id: row[0], status: row[1], total_cents: row[2], created_at: row[3], lines: lines,
      payment: payment && { status: payment[:status], auth_code: payment[:auth_code] } }
  end

  # Cancels an order and puts its stock back.
  #
  # Cancelling an already-cancelled order is a 409, not a 400 and not a 500. The request
  # was well formed and the server is healthy; the resource is simply not in a state
  # where this makes sense.
  def cancel(id)
    order = get_order(id)
    raise OrderNotCancellable.new(id, order[:status]) unless order[:status] == 'CONFIRMED'

    Database.transaction do
      order[:lines].each { |line| Catalog.release(line[:sku], line[:qty]) }
      Database.execute('UPDATE orders SET status = ? WHERE id = ?', 'CANCELLED', id)
      order.merge(status: 'CANCELLED')
    end
  end
end
