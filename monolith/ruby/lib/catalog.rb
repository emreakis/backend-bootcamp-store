# frozen_string_literal: true

require_relative 'database'
require_relative 'errors'

# MODULE: catalog — owns `products`.
#
# Public API: list_products, get_product, reserve, release.
#
# No other module may touch the `products` table. If `orders` wants a price it calls
# get_product; if it wants stock it calls reserve. Ruby enforces less of this than Go
# or Java do — `private_class_method` hides helpers, but nothing stops another file
# from writing its own SQL. Here the rule is pure discipline, which makes Ruby the
# clearest illustration of why the rule needs writing down at all.
module Catalog
  module_function

  # One page of products, plus the cursor for the next.
  #
  # Keyset pagination, not OFFSET. An offset drifts: insert a product while a client is
  # on page 2 and it either sees a row twice or misses one entirely. A cursor is a
  # position in the data, not a count of rows someone else can change.
  #
  # We ask for limit + 1 rows: if the extra one comes back there is another page.
  def list_products(limit = 20, cursor = nil)
    rows = if cursor && !cursor.empty?
             Database.query('SELECT sku, name, price_cents, stock FROM products' \
                            ' WHERE sku > ? ORDER BY sku LIMIT ?', cursor, limit + 1)
           else
             Database.query('SELECT sku, name, price_cents, stock FROM products' \
                            ' ORDER BY sku LIMIT ?', limit + 1)
           end

    has_more = rows.length > limit
    items = rows.first(limit).map { |row| to_product(row) }
    { items: items, next_cursor: has_more && !items.empty? ? items.last[:sku] : nil }
  end

  def get_product(sku)
    row = Database.query('SELECT sku, name, price_cents, stock FROM products WHERE sku = ?',
                         sku).first
    raise ProductNotFound, sku if row.nil?

    to_product(row)
  end

  # Takes `qty` units off the shelf and returns the product as it was priced.
  #
  # Nothing here mentions a transaction. Because every module shares one connection,
  # this UPDATE silently joins whatever transaction the caller opened — reserving stock
  # and writing the order become one atomic act, and neither module had to know that.
  #
  # Once catalog is a separate service, that silence becomes a lie. What replaces it is
  # a saga, and a compensating "un-reserve" that has to survive the process crashing
  # between the two calls.
  def reserve(sku, qty)
    product = get_product(sku)
    raise InsufficientStock.new(sku, qty, product[:stock]) if product[:stock] < qty

    Database.execute('UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?',
                     qty, sku, qty)
    product
  end

  # Puts stock back — used when an order is cancelled.
  def release(sku, qty)
    Database.execute('UPDATE products SET stock = stock + ? WHERE sku = ?', qty, sku)
  end

  def to_product(row)
    { sku: row[0], name: row[1], price_cents: row[2], stock: row[3] }
  end
  private_class_method :to_product
end
