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
      // TODO (exercise 3.4) — GIVE THIS CALL A TIMEOUT.
      //
      // `fetch` has no timeout. Not a long one — none at all. Its patience is
      // unbounded, and `config.catalogTimeoutMs` is read from the environment and
      // then quietly ignored.
      //
      // The web platform's answer is an AbortSignal, and modern Node gives you the
      // one-liner:
      //
      //     await fetch(url, { signal: AbortSignal.timeout(config.catalogTimeoutMs) })
      //
      // When it fires, `fetch` rejects with a TimeoutError and the socket is closed —
      // note that second half. An abort that only stops you *waiting* leaves the
      // request in flight and the connection held, which is how a service with
      // timeouts still runs out of sockets.
      //
      // Payments gets all the attention because it is the dramatic failure, but
      // catalog sits on the same checkout path: a slow catalog occupies exactly the
      // same event loop, and does it one step earlier.
      //
      // Then prove it: `docker compose pause catalog` and post an order. Before the
      // fix the request hangs; after it, you get a 503 in one second. `pause` rather
      // than `stop`, because a stopped container refuses connections instantly and a
      // paused one leaves you hanging — which is the whole point.
      // ================================================================
      response = await fetch(`${config.catalogUrl}/v1/products/${sku}`);
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
