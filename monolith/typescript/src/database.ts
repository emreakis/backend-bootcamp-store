/**
 * The single database.
 *
 * One file, one schema, every module's tables in it. `transaction()` is the thing
 * this whole bootcamp is about losing: an atomic scope that spans three modules,
 * costs nothing, and cannot half-succeed.
 *
 * Uses `node:sqlite`, which ships inside Node itself — no native module to compile,
 * no dependency to audit. It still prints an experimental warning at boot; that is
 * Node being honest, not a misconfiguration.
 */

import { Injectable, OnModuleInit } from '@nestjs/common';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync, rmSync } from 'node:fs';
import { config } from './config';

@Injectable()
export class Database implements OnModuleInit {
  private db: DatabaseSync;

  onModuleInit() {
    if (config.resetDb) {
      for (const suffix of ['', '-journal', '-wal', '-shm']) {
        rmSync(config.databasePath + suffix, { force: true });
      }
    }

    this.db = new DatabaseSync(config.databasePath);
    // Foreign keys are off by default in SQLite. Turning them on is what makes
    // order_lines.sku -> products.sku a real constraint rather than a comment.
    this.db.exec('PRAGMA foreign_keys = ON');

    // Real systems use migration tools. A teaching repo uses a file you can read,
    // and a database that is identical every time you start it.
    this.db.exec(readFileSync(config.schemaPath, 'utf8'));
    this.db.exec(readFileSync(config.seedPath, 'utf8'));
  }

  all<T>(sql: string, ...params: unknown[]): T[] {
    return this.db.prepare(sql).all(...(params as never[])) as T[];
  }

  get<T>(sql: string, ...params: unknown[]): T | undefined {
    return this.db.prepare(sql).get(...(params as never[])) as T | undefined;
  }

  run(sql: string, ...params: unknown[]): void {
    this.db.prepare(sql).run(...(params as never[]));
  }

  /**
   * Runs `fn` inside one transaction, rolling back if it throws.
   *
   * Note that no module has to pass a connection around: every service shares this
   * one object, so once BEGIN has run, every statement any module executes is part
   * of the transaction. That ambient behaviour is exactly how Spring's
   * `@Transactional` works, and it is why the Java implementation reads the same.
   *
   * Look at what it buys checkout: stock is reserved, the order is written and the
   * card is charged, and if the card is declined every one of those disappears. No
   * compensating action, no saga, no idempotency key, no partial state to reconcile
   * at 3am. One ROLLBACK.
   *
   * In Session 3 these three modules become three services with three databases and
   * this method becomes impossible to write. Everything you will learn about sagas,
   * idempotency and retries exists to buy back a fraction of what it does for free.
   */
  transaction<T>(fn: () => T): T {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const result = fn();
      this.db.exec('COMMIT');
      return result;
    } catch (error) {
      this.db.exec('ROLLBACK');
      throw error;
    }
  }
}
