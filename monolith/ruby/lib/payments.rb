# frozen_string_literal: true

require 'securerandom'
require_relative 'config'
require_relative 'database'
require_relative 'errors'

# MODULE: payments — owns `payments`.
#
# Public API: charge, find_for_order.
#
# Stands in for a real card provider. In Session 3 this module becomes a gRPC service
# and `charge` becomes a network call with a deadline, a retry policy and a circuit
# breaker in front of it. Today it is a method call: it cannot time out, it cannot be
# down, and it cannot answer twice.
module Payments
  module_function

  # The payment recorded against an order, if there is one.
  #
  # `orders` needs this to render an order, and `orders` may not read the `payments`
  # table — so the need becomes a method on this module's public API. That is the rule
  # doing its job: every cross-module need surfaces as a call, and every call is a
  # candidate to become a network hop on Saturday.
  def find_for_order(order_id)
    row = Database.query('SELECT id, order_id, amount_cents, status, auth_code FROM payments' \
                         ' WHERE order_id = ? ORDER BY created_at DESC LIMIT 1', order_id).first
    return nil if row.nil?

    { id: row[0], order_id: row[1], amount_cents: row[2], status: row[3], auth_code: row[4] }
  end

  # Charges the card, records the attempt and returns the authorisation.
  #
  # Declines are recorded too. An audit trail with only the successes in it is not an
  # audit trail — and when this becomes a remote service, "did the charge happen?" is a
  # question you will need the database to answer.
  def charge(order_id, amount_cents)
    declined = Config::PAYMENT_ALWAYS_DECLINE ||
               amount_cents > Config::PAYMENT_DECLINE_OVER_CENTS

    payment = {
      id: SecureRandom.uuid,
      order_id: order_id,
      amount_cents: amount_cents,
      status: declined ? 'DECLINED' : 'APPROVED',
      auth_code: declined ? nil : "AUTH-#{SecureRandom.hex(4).upcase}"
    }

    Database.execute(
      'INSERT INTO payments (id, order_id, amount_cents, status, auth_code, created_at)' \
      ' VALUES (?, ?, ?, ?, ?, ?)',
      payment[:id], payment[:order_id], payment[:amount_cents], payment[:status],
      payment[:auth_code], Time.now.utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    )

    if declined
      # Raising here rolls back the caller's transaction — including this INSERT. That
      # is the honest trade: we lose the record of the decline, but we cannot possibly
      # leave a confirmed order behind an unpaid card. Session 3 has to choose between
      # those two outcomes explicitly, because it can no longer have both.
      raise PaymentDeclined, "Card declined for #{amount_cents} cents " \
                             "(limit #{Config::PAYMENT_DECLINE_OVER_CENTS})."
    end

    payment
  end
end
