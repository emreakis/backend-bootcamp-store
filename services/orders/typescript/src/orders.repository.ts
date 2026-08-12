/**
 * Everything this service knows how to persist — and it is only ever its own tables.
 *
 * There is no `products` table here to join to. Catalog's data lives in a different
 * database, in a different container, behind a different set of credentials, and no
 * query in this file could reach it if it wanted to.
 */

import { Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { Pool } from 'pg';
import { config } from './config';
import type { Order, OrderLine } from './model';

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

@Injectable()
export class OrdersRepository implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(OrdersRepository.name);
  private readonly pool = new Pool({ connectionString: config.databaseUrl, max: 10 });

  async onModuleInit() {
    // Wait for the database rather than crashing if it is a second behind. compose
    // already gates startup on a healthcheck; this is the belt to that braces, because
    // in a real platform nothing promises your dependencies start first.
    const deadline = Date.now() + 30_000;
    for (;;) {
      try {
        await this.pool.query('SELECT 1');
        return;
      } catch (error) {
        if (Date.now() > deadline) throw error;
        this.logger.warn('waiting for the database');
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
    }
  }

  async onModuleDestroy() {
    await this.pool.end();
  }

  async findOrderIdByIdempotencyKey(key: string): Promise<string | null> {
    const result = await this.pool.query<{ order_id: string }>(
      'SELECT order_id FROM idempotency_keys WHERE key = $1', [key]);
    return result.rows[0]?.order_id ?? null;
  }

  /**
   * The whole write, in one short local transaction.
   *
   * This is what is left of the monolith's checkout transaction. It still spans the
   * order, its lines and the payment outcome, because those all live here — but it no
   * longer spans catalog's stock, because catalog's stock is in another database and
   * no transaction manager on earth will help you.
   *
   * Note how little time it is open for. Both network calls already happened, outside.
   * See the comment on `OrdersService.checkout`.
   *
   * Note also the explicit `connect()`. `pool.query` grabs a connection per statement
   * and gives it straight back, so BEGIN and COMMIT issued that way could land on two
   * different connections and quietly do nothing. A transaction is a property of a
   * connection, not of a pool.
   */
  async persist(id: string, createdAt: Date, totalCents: number, lines: OrderLine[],
                paymentStatus: string, authCode: string | null,
                idempotencyKey: string | null): Promise<void> {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');

      await client.query(
        `INSERT INTO orders (id, status, total_cents, created_at, payment_status,
                             payment_auth_code) VALUES ($1, $2, $3, $4, $5, $6)`,
        [id, 'CONFIRMED', totalCents, createdAt, paymentStatus, authCode]);

      for (const line of lines) {
        await client.query(
          `INSERT INTO order_lines (order_id, sku, name, unit_cents, qty)
           VALUES ($1, $2, $3, $4, $5)`,
          [id, line.sku, line.name, line.unit_cents, line.qty]);
      }

      // Written in the SAME transaction as the order. If it were a second, separate
      // write, a crash between the two would leave an order whose idempotency key was
      // never recorded — and the client's retry would cheerfully create a duplicate.
      // Atomicity is still available here; it is only cross-service atomicity that is
      // gone.
      if (idempotencyKey) {
        await client.query(
          'INSERT INTO idempotency_keys (key, order_id, created_at) VALUES ($1, $2, $3)',
          [idempotencyKey, id, createdAt]);
      }

      await client.query('COMMIT');
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    } finally {
      client.release();
    }
  }

  async findOrder(id: string): Promise<Order | null> {
    // Not a uuid at all, so it cannot name an order. A 404 rather than a 500 or a
    // Postgres `invalid input syntax for type uuid` leaking out through the driver.
    if (!UUID_PATTERN.test(id)) return null;

    const header = await this.pool.query(
      `SELECT id, status, total_cents, created_at, payment_status, payment_auth_code
       FROM orders WHERE id = $1`, [id]);
    if (header.rowCount === 0) return null;

    const lines = await this.pool.query(
      'SELECT sku, name, unit_cents, qty FROM order_lines WHERE order_id = $1 ORDER BY sku',
      [id]);

    const row = header.rows[0];
    return {
      id: row.id,
      status: row.status,
      // `total_cents` is a BIGINT, and node-postgres hands BIGINTs back as strings
      // because a JS number stops being exact past 2^53. Money in minor units will
      // never come close, so Number() is safe here — but the string is the driver
      // being careful, not the driver being annoying.
      total_cents: Number(row.total_cents),
      created_at: isoSeconds(row.created_at),
      lines: lines.rows.map((line) => ({
        sku: line.sku,
        name: line.name,
        unit_cents: Number(line.unit_cents),
        qty: Number(line.qty),
      })),
      payment: row.payment_status
        ? { status: row.payment_status, auth_code: row.payment_auth_code }
        : null,
    };
  }

  async markCancelled(id: string): Promise<void> {
    await this.pool.query('UPDATE orders SET status = $1 WHERE id = $2', ['CANCELLED', id]);
  }
}

/** RFC 3339, UTC, seconds precision — what the contract says. */
export function isoSeconds(moment: Date): string {
  return `${moment.toISOString().slice(0, 19)}Z`;
}
