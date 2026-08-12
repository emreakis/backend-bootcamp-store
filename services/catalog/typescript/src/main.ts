/**
 * CATALOG — the read side of the store, and the simplest service in the system.
 *
 * Small enough to read in two files, which is why it is the one to read first.
 * Everything here satisfies contracts/catalog.v1.yaml; if this file and that file
 * disagree, this file is wrong.
 *
 * Compare it with `monolith/typescript/src/catalog/`. The SQL is identical. What
 * changed is everything around it: its own database, its own process, its own
 * deployment, and a `reserve` method that no longer exists because stock cannot be
 * taken off a shelf in one database inside a transaction that lives in another.
 */

import 'reflect-metadata';
import {
  ArgumentsHost, Catch, Controller, ExceptionFilter, Get, HttpException,
  Injectable, Logger, Module, OnModuleDestroy, OnModuleInit, Param, Query,
} from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import type { Request, Response } from 'express';
import { Pool } from 'pg';

const config = {
  implementation: 'typescript',
  port: Number(process.env.PORT ?? 8000),
  databaseUrl: process.env.DATABASE_URL ?? 'postgres://store:store@localhost:5433/catalog',
};

const PROBLEM_BASE = 'https://bootcamp.backendguru.io/problems/';

interface Product {
  sku: string;
  name: string;
  price_cents: number;
  stock: number;
}

/** Signals a failure this service designed, as opposed to one that happened to it. */
class DomainError extends Error {
  constructor(readonly kind: string, readonly title: string,
              readonly status: number, readonly detail: string) {
    super(detail);
  }
}

@Injectable()
class Catalog implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(Catalog.name);
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

  /**
   * Keyset pagination. An offset would drift under concurrent inserts; a cursor is a
   * position in the data rather than a count of rows someone else can change.
   *
   * Ask for limit + 1 rows: if the extra one comes back, there is another page.
   */
  async list(limit: number, cursor?: string) {
    const rows = cursor
      ? await this.pool.query(
          'SELECT sku, name, price_cents, stock FROM products' +
          ' WHERE sku > $1 ORDER BY sku LIMIT $2', [cursor, limit + 1])
      : await this.pool.query(
          'SELECT sku, name, price_cents, stock FROM products ORDER BY sku LIMIT $1',
          [limit + 1]);

    const hasMore = rows.rowCount! > limit;
    const items: Product[] = rows.rows.slice(0, limit).map(toProduct);
    return {
      items,
      // null on the last page, not '' and not undefined. The contract says null, and a
      // key that disappears entirely is a different document from one holding null.
      next_cursor: hasMore && items.length ? items[items.length - 1].sku : null,
    };
  }

  async get(sku: string): Promise<Product> {
    const rows = await this.pool.query(
      'SELECT sku, name, price_cents, stock FROM products WHERE sku = $1', [sku]);
    if (rows.rowCount === 0) {
      throw new DomainError('product-not-found', 'Product not found', 404,
        `No product with sku '${sku}'.`);
    }
    return toProduct(rows.rows[0]);
  }
}

/**
 * `price_cents` and `stock` are BIGINTs, and node-postgres hands BIGINTs back as
 * strings because a JS number stops being exact past 2^53. Money in minor units will
 * never come close, so Number() is safe here — but the string is the driver being
 * careful, not the driver being annoying, and a service that forgets this ships
 * `"price_cents": "18900"` to a client expecting a number.
 */
function toProduct(row: any): Product {
  return {
    sku: row.sku,
    name: row.name,
    price_cents: Number(row.price_cents),
    stock: Number(row.stock),
  };
}

@Controller()
class CatalogController {
  constructor(private readonly catalog: Catalog) {}

  /**
   * Liveness only — it does not touch the database.
   *
   * Tempting to run `SELECT 1` here. Don't: if this endpoint failed whenever Postgres
   * hiccupped, the platform would start killing catalog pods during a database blip,
   * removing capacity exactly when the system is least able to spare it.
   */
  @Get('health')
  health() {
    return { status: 'ok', implementation: config.implementation };
  }

  @Get('v1/products')
  list(@Query('limit') rawLimit?: string, @Query('cursor') cursor?: string) {
    // Nest hands query parameters over as strings and has no opinion about their
    // range. The contract declares 1..100 and says an out-of-range value is a 400 in
    // the usual envelope, so that check happens here, by hand, rather than being left
    // to a framework default that differs in all six languages.
    const limit = rawLimit === undefined ? 20 : Number(rawLimit);
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
      throw new DomainError('validation-failed', 'Validation failed', 400,
        'limit must be an integer between 1 and 100.');
    }
    return this.catalog.list(limit, cursor);
  }

  /**
   * The call `orders` makes during checkout.
   *
   * Its 404 is the most consequential response in this service. Orders has to turn it
   * into a designed order rejection — so it must be unambiguous, carry the sku that
   * was missing, and never arrive as a 500. A dependency that fails clearly is a
   * dependency you can build on.
   */
  @Get('v1/products/:sku')
  get(@Param('sku') sku: string) {
    return this.catalog.get(sku);
  }
}

/** One error envelope, everywhere — RFC 9457, exactly as contracts/problem.yaml says. */
@Catch()
class ProblemFilter implements ExceptionFilter {
  private readonly logger = new Logger(ProblemFilter.name);

  catch(exception: unknown, host: ArgumentsHost) {
    const http = host.switchToHttp();
    const request = http.getRequest<Request>();
    const response = http.getResponse<Response>();

    let kind: string, title: string, status: number, detail: string;

    if (exception instanceof DomainError) {
      ({ kind, title, status, detail } = exception);
    } else if (exception instanceof HttpException && exception.getStatus() === 404) {
      status = 404;
      kind = 'product-not-found';
      title = 'Product not found';
      detail = `No product with sku '${request.path}'.`;
    } else {
      // Anything unnamed is a bug. 500, and the detail stays in our logs — never in a
      // response body, where it becomes a client's problem to parse and an attacker's
      // to read.
      this.logger.error(`unhandled error on ${request.path}`, exception as Error);
      status = 500;
      kind = 'internal-error';
      title = 'Internal server error';
      detail = 'The request could not be completed.';
    }

    response
      .status(status)
      .setHeader('Content-Type', 'application/problem+json')
      .json({ type: PROBLEM_BASE + kind, title, status, detail, instance: request.path });
  }
}

@Module({ controllers: [CatalogController], providers: [Catalog] })
class AppModule {}

async function bootstrap() {
  const app = await NestFactory.create(AppModule, { logger: ['log', 'warn', 'error'] });
  app.useGlobalFilters(new ProblemFilter());

  // 0.0.0.0, not localhost. A process that binds to the loopback interface is
  // unreachable from outside its own container no matter how the network is wired.
  await app.listen(config.port, '0.0.0.0');
  new Logger('Bootstrap').log(
    `catalog (${config.implementation}) listening on :${config.port}`);
}

bootstrap();
