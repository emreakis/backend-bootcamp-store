/**
 * One user action, three services, two protocols.
 *
 * Open `monolith/typescript/src/orders/orders.service.ts` next to this file. The steps
 * are the same three: price the lines, charge the card, write the order. Almost every
 * line of difference is a consequence of those steps now crossing a network.
 */

import { Injectable, Logger } from '@nestjs/common';
import { randomUUID } from 'node:crypto';
import { CatalogClient } from './catalog.client';
import { OrderNotCancellable, OrderNotFound, ValidationFailed } from './errors';
import type { Order, OrderItem, OrderLine } from './model';
import { isoSeconds, OrdersRepository } from './orders.repository';
import { PaymentsClient } from './payments.client';

@Injectable()
export class OrdersService {
  private readonly logger = new Logger(OrdersService.name);

  constructor(
    private readonly repository: OrdersRepository,
    private readonly catalog: CatalogClient,
    private readonly payments: PaymentsClient,
  ) {}

  /**
   * NOTE WHAT IS MISSING FROM THIS METHOD: a transaction around the whole thing.
   *
   * That is deliberate, and it is the single most important structural decision in
   * this service.
   *
   * The obvious move is to take a connection at the top and hold it to the bottom, the
   * way the monolith does. Do that and you hold a database connection open across two
   * network calls. A slow payments service then does not merely make checkout slow —
   * it pins one connection per in-flight order until the pool is empty (ten, here), at
   * which point every other endpoint in this service stops working too, including the
   * ones that never touch payments. You would have converted a payments outage into a
   * total outage, via your connection pool.
   *
   * So: talk to the network first, hold no locks while doing it, and open a short
   * local transaction only once you have everything you need to write.
   *
   * The cost is that steps 1-2 and step 3 are no longer atomic together. If this
   * process dies between the charge and the insert, the customer is charged for an
   * order that does not exist. That is a real hole, and the honest answers to it — an
   * outbox, a reconciliation job, a saga — are the module after this bootcamp. The
   * monolith closed it with one keyword. Nothing here closes it for free.
   */
  async checkout(items: OrderItem[] | undefined, idempotencyKey?: string): Promise<Order> {
    const basket = validate(items);

    // Did we already do exactly this? A dropped response is indistinguishable from a
    // failed request, so a good client retries — and this is what makes that retry safe
    // rather than expensive.
    if (idempotencyKey) {
      const seen = await this.repository.findOrderIdByIdempotencyKey(idempotencyKey);
      if (seen) {
        this.logger.log(`idempotency_key=${idempotencyKey} REPLAYED -> order=${seen}`);
        return this.getOrder(seen);
      }
    }

    const orderId = randomUUID();
    const createdAt = new Date(Math.floor(Date.now() / 1000) * 1000);

    // 1. Price every line against catalog, over REST. A 404 here becomes a designed
    //    order rejection; an unreachable catalog becomes a 503.
    //
    //    Sequential on purpose, not Promise.all. Pricing three lines in parallel would
    //    be faster and would also triple the burst this service puts on catalog for a
    //    single checkout — and the first thing a struggling dependency needs is fewer
    //    concurrent requests, not more. Parallelism is a decision, not a default.
    const lines: OrderLine[] = [];
    let totalCents = 0;
    for (const item of basket) {
      const product = await this.catalog.fetch(item.sku);
      lines.push({
        sku: product.sku,
        name: product.name,
        unit_cents: product.price_cents,
        qty: item.qty,
      });
      totalCents += product.price_cents * item.qty;
    }

    // 2. Charge, over gRPC.
    //
    //    The idempotency key handed downstream is the ORDER ID when the client did not
    //    supply one — stable across this service's own internal retries, which is what
    //    exercise 3.2 depends on. It is deliberately NOT stable across two separate
    //    client calls with no Idempotency-Key: that is the client choosing to have no
    //    protection, and the contract says so out loud.
    const payment = await this.payments.charge(
      orderId, totalCents, idempotencyKey || orderId);

    // 3. Now, and only now, a short local transaction.
    await this.repository.persist(orderId, createdAt, totalCents, lines,
      payment.status, payment.auth_code, idempotencyKey ?? null);

    this.logger.log(`order=${orderId} CONFIRMED total=${totalCents} lines=${lines.length}`);
    return {
      id: orderId,
      status: 'CONFIRMED',
      total_cents: totalCents,
      created_at: isoSeconds(createdAt),
      lines,
      payment,
    };
  }

  async getOrder(id: string): Promise<Order> {
    const order = await this.repository.findOrder(id);
    if (!order) throw new OrderNotFound(id);
    return order;
  }

  /**
   * Cancel an order.
   *
   * Shorter than the monolith's version, because there is no stock to put back — this
   * system never took any.
   *
   * What it also does not do is refund the card, and that omission is worth naming
   * rather than hiding. A refund is a second call to a service that can be down, and
   * doing it inline would make cancellation fail whenever payments is unwell. It
   * belongs on a queue, retried until it succeeds. That is the same "after the charge,
   * not in front of the customer" pattern as confirmation emails and inventory — the
   * module after this bootcamp.
   */
  async cancel(id: string): Promise<Order> {
    const order = await this.getOrder(id);
    if (order.status !== 'CONFIRMED') {
      throw new OrderNotCancellable(id, order.status);
    }
    await this.repository.markCancelled(id);
    this.logger.log(`order=${id} CANCELLED`);
    return { ...order, status: 'CANCELLED' };
  }
}

/** Narrows the untrusted request shape into one the rest of the service can rely on. */
function validate(items: OrderItem[] | undefined): { sku: string; qty: number }[] {
  if (!Array.isArray(items) || items.length === 0) {
    throw new ValidationFailed('An order needs at least one item.');
  }
  return items.map((item) => {
    if (typeof item?.sku !== 'string' || item.sku.length === 0) {
      throw new ValidationFailed('Every item needs a sku.');
    }
    if (typeof item.qty !== 'number' || !Number.isInteger(item.qty) || item.qty < 1) {
      throw new ValidationFailed('Every item needs a qty of at least 1.');
    }
    return { sku: item.sku, qty: item.qty };
  });
}
