/**
 * MODULE: catalog — owns `products`.
 *
 * Public API: listProducts, getProduct, reserve, release.
 *
 * No other module may touch the `products` table. If `orders` wants a price it
 * calls getProduct; if it wants stock it calls reserve. Nest enforces the half of
 * this that a framework can: a service is only injectable elsewhere if its module
 * exports it, so this class's public methods are the only surface another module
 * can reach. The other half — that the string 'products' appears in no other file —
 * is discipline, and it is what makes the Session 3 split a mechanical exercise
 * rather than a rewrite.
 */

import { Injectable } from '@nestjs/common';
import { Database } from '../database';
import { InsufficientStock, ProductNotFound } from '../errors';

export interface Product {
  sku: string;
  name: string;
  price_cents: number;
  stock: number;
}

@Injectable()
export class CatalogService {
  constructor(private readonly db: Database) {}

  /**
   * One page of products, plus the cursor for the next.
   *
   * Keyset pagination, not OFFSET. An offset drifts: insert a product while a
   * client is on page 2 and it either sees a row twice or misses one entirely. A
   * cursor is a position in the data, not a count of rows someone else can change.
   *
   * We ask for limit + 1 rows: if the extra one comes back there is another page.
   */
  listProducts(limit = 20, cursor?: string): { items: Product[]; next_cursor: string | null } {
    const rows = cursor
      ? this.db.all<Product>(
          'SELECT sku, name, price_cents, stock FROM products WHERE sku > ? ORDER BY sku LIMIT ?',
          cursor, limit + 1)
      : this.db.all<Product>(
          'SELECT sku, name, price_cents, stock FROM products ORDER BY sku LIMIT ?',
          limit + 1);

    const hasMore = rows.length > limit;
    const items = rows.slice(0, limit);
    return {
      items,
      next_cursor: hasMore && items.length ? items[items.length - 1].sku : null,
    };
  }

  getProduct(sku: string): Product {
    const product = this.db.get<Product>(
      'SELECT sku, name, price_cents, stock FROM products WHERE sku = ?', sku);
    if (!product) throw new ProductNotFound(sku);
    return product;
  }

  /**
   * Takes `qty` units off the shelf and returns the product as it was priced.
   *
   * Nothing here mentions a transaction. Because every service shares one
   * connection, this UPDATE silently joins whatever transaction the caller opened —
   * reserving stock and writing the order become one atomic act, and neither module
   * had to know that.
   *
   * Once catalog is a separate service, that silence becomes a lie. What replaces
   * it is a saga, and a compensating "un-reserve" that has to survive the process
   * crashing between the two calls.
   */
  reserve(sku: string, qty: number): Product {
    const product = this.getProduct(sku);
    if (product.stock < qty) throw new InsufficientStock(sku, qty, product.stock);

    this.db.run(
      'UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?', qty, sku, qty);
    return product;
  }

  /** Puts stock back — used when an order is cancelled. */
  release(sku: string, qty: number): void {
    this.db.run('UPDATE products SET stock = stock + ? WHERE sku = ?', qty, sku);
  }
}
