/**
 * MODULE: payments — owns `payments`.
 *
 * Public API: charge, findForOrder.
 *
 * Stands in for a real card provider. In Session 3 this module becomes a gRPC
 * service and `charge` becomes a network call with a deadline, a retry policy and a
 * circuit breaker in front of it. Today it is a method call: it cannot time out, it
 * cannot be down, and it cannot answer twice.
 */

import { Injectable } from '@nestjs/common';
import { randomUUID } from 'node:crypto';
import { Database } from '../database';
import { config } from '../config';
import { PaymentDeclined } from '../errors';

export interface Payment {
  id: string;
  order_id: string;
  amount_cents: number;
  status: 'APPROVED' | 'DECLINED';
  auth_code: string | null;
}

@Injectable()
export class PaymentsService {
  constructor(private readonly db: Database) {}

  /**
   * The payment recorded against an order, if there is one.
   *
   * `orders` needs this to render an order, and `orders` may not read the
   * `payments` table — so the need becomes a method on this module's public API.
   * That is the rule doing its job: every cross-module need surfaces as a call, and
   * every call is a candidate to become a network hop on Saturday.
   */
  findForOrder(orderId: string): Payment | null {
    return this.db.get<Payment>(
      'SELECT id, order_id, amount_cents, status, auth_code FROM payments' +
      ' WHERE order_id = ? ORDER BY created_at DESC LIMIT 1', orderId) ?? null;
  }

  /**
   * Charges the card, records the attempt and returns the authorisation.
   *
   * Declines are recorded too. An audit trail with only the successes in it is not
   * an audit trail — and when this becomes a remote service, "did the charge
   * happen?" is a question you will need the database to answer.
   */
  charge(orderId: string, amountCents: number): Payment {
    const declined =
      config.paymentAlwaysDecline || amountCents > config.paymentDeclineOverCents;

    const payment: Payment = {
      id: randomUUID(),
      order_id: orderId,
      amount_cents: amountCents,
      status: declined ? 'DECLINED' : 'APPROVED',
      auth_code: declined ? null : `AUTH-${randomUUID().replace(/-/g, '').slice(0, 8).toUpperCase()}`,
    };

    this.db.run(
      'INSERT INTO payments (id, order_id, amount_cents, status, auth_code, created_at)' +
      ' VALUES (?, ?, ?, ?, ?, ?)',
      payment.id, payment.order_id, payment.amount_cents, payment.status,
      payment.auth_code, new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'));

    if (declined) {
      // Throwing here rolls back the caller's transaction — including this INSERT.
      // That is the honest trade: we lose the record of the decline, but we cannot
      // possibly leave a confirmed order behind an unpaid card. Session 3 has to
      // choose between those two outcomes explicitly, because it can no longer have
      // both.
      throw new PaymentDeclined(
        `Card declined for ${amountCents} cents (limit ${config.paymentDeclineOverCents}).`);
    }
    return payment;
  }
}
