/**
 * Configuration comes from the environment. Never from code.
 *
 * Twelve-factor, and the reason it matters here: the artifact you run in Session 3
 * is identical in dev and prod. Only the environment around it changes. Hard-code
 * one address and that stops being true.
 */

const str = (key: string, fallback: string) => process.env[key] ?? fallback;
const num = (key: string, fallback: number) => {
  const parsed = Number(process.env[key]);
  return Number.isFinite(parsed) ? parsed : fallback;
};

export const config = {
  implementation: 'typescript',
  port: num('PORT', 8080),
  databasePath: str('DATABASE_PATH', './store.db'),
  schemaPath: str('SCHEMA_PATH', '../../db/schema.sql'),
  seedPath: str('SEED_PATH', '../../db/seed.sql'),
  resetDb: str('RESET_DB', 'true') !== 'false',

  // The payment stub is deterministic on purpose. A demo that fails randomly
  // teaches nothing; a demo that fails on command teaches one thing at a time.
  paymentDeclineOverCents: num('PAYMENT_DECLINE_OVER_CENTS', 500_000),
  paymentAlwaysDecline: str('PAYMENT_ALWAYS_DECLINE', 'false') === 'true',
};
