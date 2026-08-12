/**
 * The REST half of this service's dependencies.
 *
 * In the monolith this was `catalog.getProduct(db, sku)` — a function call that could
 * not fail on its own. It is now an HTTP request over a network, and every one of the
 * eight fallacies applies to it.
 */

import { Injectable, Logger } from '@nestjs/common';
import { config } from './config';
import { CatalogUnavailable, ProductNotFound } from './errors';
import type { ProductSnapshot } from './model';

@Injectable()
export class CatalogClient {
  private readonly logger = new Logger(CatalogClient.name);

  constructor() {
    this.logger.log(
      `catalog client -> ${config.catalogUrl} (timeout ${config.catalogTimeoutMs} ms)`);
  }

  /**
   * Price one sku.
   *
   * Three outcomes, and all three are designed:
   *
   *   - the product exists — we take its name and price and stop caring about it;
   *   - catalog says 404 — a *designed order rejection*, not a 500. Passing a
   *     dependency's status straight through would be lazy; letting it become a stack
   *     trace would be worse;
   *   - catalog cannot be reached — 503, because the customer did nothing wrong.
   */
  async fetch(sku: string): Promise<ProductSnapshot> {
    let response: Response;
    try {
      // ================================================================
      // EXERCISE 3.4 — the timeout.
      //
      // The web platform's answer is an AbortSignal, and modern Node gives you the
      // one-liner. When it fires, `fetch` rejects with a TimeoutError AND the socket is
      // closed — note that second half. An abort that only stops you *waiting* leaves
      // the request in flight and the connection held, which is how a service that has
      // timeouts still runs out of sockets.
      //
      // One number covers the whole round trip here, which is enough for a teaching
      // system. `fetch` gives you no way to split connect from read; when you need
      // that in Node you drop to undici's Agent and set connectTimeout and
      // headersTimeout separately. Different failures with different causes, and only
      // the second is what `docker compose pause catalog` produces.
      //
      // Prove it: `docker compose pause catalog` and post an order. Before this change
      // the request hung; now it is a 503 in one second.
      // ================================================================
      response = await fetch(`${config.catalogUrl}/v1/products/${sku}`, {
        signal: AbortSignal.timeout(config.catalogTimeoutMs),
      });
    } catch (unreachable) {
      // Connection refused, DNS failure, or an abort — the last of which is only
      // reachable once exercise 3.4 is done.
      this.logger.warn(`catalog unreachable for sku=${sku}: ${unreachable}`);
      throw new CatalogUnavailable(
        'The catalog service could not be reached. No order was placed.');
    }

    if (response.status === 404) {
      throw new ProductNotFound(sku);
    }
    if (!response.ok) {
      this.logger.warn(`catalog answered ${response.status} for sku=${sku}`);
      throw new CatalogUnavailable(
        'The catalog service returned an unusable response. No order was placed.');
    }

    const body = (await response.json()) as ProductSnapshot;
    return { sku: body.sku, name: body.name, price_cents: body.price_cents };
  }
}
