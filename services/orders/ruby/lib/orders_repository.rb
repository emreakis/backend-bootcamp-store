# frozen_string_literal: true

require 'pg'
require 'securerandom'
require 'time'
require_relative 'config'

# Everything this service knows how to persist — and it is only ever its own tables.
#
# There is no `products` table here to join to. Catalog's data lives in a different
# database, in a different container, behind a different set of credentials, and no
# query in this file could reach it if it wanted to.
module OrdersRepository
  UUID = /\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\z/i

  module_function

  # A connection per request, from a pool keyed on the current thread.
  #
  # puma serves this app from a thread pool and a PG::Connection is not safe to share
  # across threads, so each one gets its own. Crude compared with the managed pools the
  # other five implementations use — and visible, which is the point: something has to
  # own the question "how many connections does this process hold open", and if you do
  # not answer it your framework answered it for you.
  def connection
    Thread.current[:pg] ||= PG.connect(Config::DATABASE_URL)
  end

  # Wait for the database rather than crashing if it is a second behind. compose already
  # gates startup on a healthcheck; this is the belt to that braces, because in a real
  # platform nothing promises your dependencies start first.
  def wait_for_database!
    deadline = Time.now + 30
    begin
      PG.connect(Config::DATABASE_URL).close
    rescue PG::Error => e
      raise e if Time.now > deadline

      warn 'waiting for the database'
      sleep 0.5
      retry
    end
  end

  def find_order_id_by_idempotency_key(key)
    result = connection.exec_params(
      'SELECT order_id FROM idempotency_keys WHERE key = $1', [key]
    )
    result.ntuples.zero? ? nil : result[0]['order_id']
  end

  # The whole write, in one short local transaction.
  #
  # This is what is left of the monolith's checkout transaction. It still spans the
  # order, its lines and the payment outcome, because those all live here — but it no
  # longer spans catalog's stock, because catalog's stock is in another database and no
  # transaction manager on earth will help you.
  #
  # Note how little time it is open for. Both network calls already happened, outside.
  # See the comment on OrdersService.checkout.
  def persist(id, created_at, total_cents, lines, payment, idempotency_key)
    connection.transaction do |conn|
      conn.exec_params(
        'INSERT INTO orders (id, status, total_cents, created_at, payment_status,' \
        ' payment_auth_code) VALUES ($1, $2, $3, $4, $5, $6)',
        [id, 'CONFIRMED', total_cents, created_at, payment[:status], payment[:auth_code]]
      )

      lines.each do |line|
        conn.exec_params(
          'INSERT INTO order_lines (order_id, sku, name, unit_cents, qty)' \
          ' VALUES ($1, $2, $3, $4, $5)',
          [id, line[:sku], line[:name], line[:unit_cents], line[:qty]]
        )
      end

      # Written in the SAME transaction as the order. If it were a second, separate
      # write, a crash between the two would leave an order whose idempotency key was
      # never recorded — and the client's retry would cheerfully create a duplicate.
      # Atomicity is still available here; it is only cross-service atomicity that is
      # gone.
      next if idempotency_key.nil? || idempotency_key.empty?

      conn.exec_params(
        'INSERT INTO idempotency_keys (key, order_id, created_at) VALUES ($1, $2, $3)',
        [idempotency_key, id, created_at]
      )
    end
  end

  def find_order(id)
    # Not a uuid at all, so it cannot name an order. A 404 rather than a 500 or a
    # Postgres `invalid input syntax for type uuid` leaking out through the driver.
    return nil unless id.match?(UUID)

    header = connection.exec_params(
      'SELECT id, status, total_cents, created_at, payment_status, payment_auth_code' \
      ' FROM orders WHERE id = $1', [id]
    )
    return nil if header.ntuples.zero?

    row = header[0]
    lines = connection.exec_params(
      'SELECT sku, name, unit_cents, qty FROM order_lines WHERE order_id = $1 ORDER BY sku',
      [id]
    )

    {
      id: row['id'],
      status: row['status'],
      # Postgres hands everything back as a string. BIGINT included, and silently
      # comparing one of those to a number is a Ruby afternoon nobody enjoys.
      total_cents: row['total_cents'].to_i,
      created_at: iso(Time.parse(row['created_at'])),
      lines: lines.map do |line|
        { sku: line['sku'], name: line['name'],
          unit_cents: line['unit_cents'].to_i, qty: line['qty'].to_i }
      end,
      payment: row['payment_status'] &&
        { status: row['payment_status'], auth_code: row['payment_auth_code'] }
    }
  end

  def mark_cancelled(id)
    connection.exec_params('UPDATE orders SET status = $1 WHERE id = $2', ['CANCELLED', id])
  end

  # RFC 3339, UTC, seconds precision — what the contract says.
  def iso(moment)
    moment.utc.strftime('%Y-%m-%dT%H:%M:%SZ')
  end
end
