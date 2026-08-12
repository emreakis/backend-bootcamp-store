/**
 * MODULE: orders — owns `orders` and `order_lines`.
 *
 * Public API: checkout, getOrder, cancel.
 *
 * The orchestrator, and the only module that depends on the other two. Trace the
 * call chain in `checkout` — it is the same chain Session 3 draws across three
 * services, except that here every arrow is a method call that cannot fail on its
 * own.
 */

import { Injectable } from '@nestjs/common';
import { randomUUID } from 'node:crypto';
import { Database } from '../database';
import { CatalogService } from '../catalog/catalog.service';
import { PaymentsService } from '../payments/payments.service';
import { OrderNotCancellable, OrderNotFound, ValidationFailed } from '../errors';

export interface OrderItem {
  sku: string;
  qty: number;
}

export interface OrderLine {
  sku: string;
  name: string;
  unit_cents: number;
  qty: number;
}

export interface Order {
  id: string;
  status: string;
  total_cents: number;
  created_at: string;
  lines: OrderLine[];
  payment: { status: string; auth_code: string | null } | null;
}

@Injectable()
export class OrdersService {
  constructor(
    private readonly db: Database,
    // Injected because CatalogModule and PaymentsModule export them. This
    // constructor is the dependency arrow on the Session 1 architecture diagram.
    private readonly catalog: CatalogService,
    private readonly payments: PaymentsService,
  ) {}

  /**
   * One user action, three modules, one transaction.
   *
   * Read this next to the Session 3 diagram of the same flow. The steps are
   * identical. The difference is that every step here either happens or does not
   * happen, together, and there is no state in between for anyone to observe.
   */
  checkout(items: OrderItem[]): Order {
    if (!Array.isArray(items) || items.length === 0) {
      throw new ValidationFailed('An order needs at least one item.');
    }
    for (const item of items) {
      if (!item?.sku) throw new ValidationFailed('Every item needs a sku.');
      if (!Number.isInteger(item.qty) || item.qty < 1) {
        throw new ValidationFailed('Every item needs a qty of at least 1.');
      }
    }

    const id = randomUUID();
    const createdAt = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');

    return this.db.transaction(() => {
      // 1. Reserve stock and capture the price AS IT IS NOW. Calling into catalog,
      //    never touching its table.
      const lines: OrderLine[] = items.map((item) => {
        const product = this.catalog.reserve(item.sku, item.qty);
        return {
          sku: product.sku,
          name: product.name,
          unit_cents: product.price_cents,
          qty: item.qty,
        };
      });

      const totalCents = lines.reduce((sum, line) => sum + line.unit_cents * line.qty, 0);

      // 2. Write the order. The line rows copy name and unit_cents on purpose: an
      //    order records what was sold, not what the catalog says next week.
      this.db.run(
        'INSERT INTO orders (id, status, total_cents, created_at) VALUES (?, ?, ?, ?)',
        id, 'CONFIRMED', totalCents, createdAt);
      for (const line of lines) {
        this.db.run(
          'INSERT INTO order_lines (order_id, sku, name, unit_cents, qty) VALUES (?, ?, ?, ?, ?)',
          id, line.sku, line.name, line.unit_cents, line.qty);
      }

      // 3. Charge. A decline throws, the transaction rolls back, and the stock
      //    reserved in step 1 is back on the shelf without anyone writing code to
      //    put it there. That last clause is what Session 3 costs you.
      const payment = this.payments.charge(id, totalCents);

      return {
        id, status: 'CONFIRMED', total_cents: totalCents, created_at: createdAt, lines,
        payment: { status: payment.status, auth_code: payment.auth_code },
      };
    });
  }

  getOrder(id: string): Order {
    const row = this.db.get<{ id: string; status: string; total_cents: number; created_at: string }>(
      'SELECT id, status, total_cents, created_at FROM orders WHERE id = ?', id);
    if (!row) throw new OrderNotFound(id);

    const lines = this.db.all<OrderLine>(
      'SELECT sku, name, unit_cents, qty FROM order_lines WHERE order_id = ? ORDER BY sku', id);

    // Again: through the module's API, not its table.
    const payment = this.payments.findForOrder(id);

    return {
      ...row,
      lines,
      payment: payment ? { status: payment.status, auth_code: payment.auth_code } : null,
    };
  }

  /**
   * Cancels an order and puts its stock back.
   *
   * Cancelling an already-cancelled order is a 409, not a 400 and not a 500. The
   * request was well formed and the server is healthy; the resource is simply not
   * in a state where this makes sense.
   */
  cancel(id: string): Order {
    const order = this.getOrder(id);
    if (order.status !== 'CONFIRMED') throw new OrderNotCancellable(id, order.status);

    return this.db.transaction(() => {
      for (const line of order.lines) {
        this.catalog.release(line.sku, line.qty);
      }
      this.db.run('UPDATE orders SET status = ? WHERE id = ?', 'CANCELLED', id);
      return { ...order, status: 'CANCELLED' };
    });
  }
}
