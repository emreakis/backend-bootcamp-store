/**
 * Configuration from the environment. Never from code.
 *
 * Seven values, five of them about what to do when somebody else fails. Catalog has
 * two. That ratio is the price of being the service in the middle.
 *
 * Note what is NOT here: a hostname anybody typed. `catalog` and `payments` are
 * service names the platform resolves — compose's DNS today, a Kubernetes Service
 * tomorrow, with no code change. Hard-coding an address is how you make an image that
 * only runs in one place.
 */

const num = (key: string, fallback: number): number => {
  const raw = process.env[key];
  const parsed = raw ? Number(raw) : NaN;
  return Number.isFinite(parsed) ? parsed : fallback;
};

export const config = {
  implementation: 'typescript',

  port: num('PORT', 8080),
  databaseUrl: process.env.DATABASE_URL ?? 'postgres://store:store@localhost:5434/orders',

  catalogUrl: process.env.CATALOG_URL ?? 'http://localhost:8000',
  paymentsAddr: process.env.PAYMENTS_ADDR ?? 'localhost:50051',

  // Policy, not guesswork. 2000 ms is a statement about how long a checkout may wait
  // on a charge, made by the people who own checkout — not an estimate of how fast
  // payments happens to be today.
  //
  // All four are read here and then, in this starter, quietly ignored. That is
  // exercise 3.
  catalogTimeoutMs: num('CATALOG_TIMEOUT_MS', 1000),
  paymentsTimeoutMs: num('PAYMENTS_TIMEOUT_MS', 2000),
  paymentsRetryMax: num('PAYMENTS_RETRY_MAX', 2),
  breakerFailureThreshold: num('BREAKER_FAILURE_THRESHOLD', 5),
  breakerResetMs: num('BREAKER_RESET_MS', 10000),
} as const;
