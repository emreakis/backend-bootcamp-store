/**
 * The shapes this service reads and writes.
 *
 * Every field on the wire is snake_case because contracts/orders.v1.yaml says so, and
 * these interfaces are written that way rather than being camelCase with a mapping
 * layer. That is a deliberate choice for a repo where six languages have to produce
 * byte-identical JSON: one of them always ends up doing the translation, and doing it
 * in the type is cheaper than doing it in a serializer configuration nobody can see.
 *
 * (The Java implementation makes the other choice — camelCase records plus one
 * naming-strategy line — and paid for it with a bug. See its README.)
 *
 * They live in one file because they are data, not behaviour, and reading them
 * together is how you see the contract.
 */

/** One line of an incoming checkout request. Everything optional: this is untrusted. */
export interface OrderItem {
  sku?: string;
  qty?: number;
}

export interface CreateOrderRequest {
  items?: OrderItem[];
}

/**
 * What catalog told us, at the moment we asked.
 *
 * Deliberately narrower than catalog's own product: orders has no business carrying a
 * stock level around, because nothing here acts on it. Take from a dependency only
 * what you use — every extra field is a thing that can change under you and a coupling
 * you did not need.
 */
export interface ProductSnapshot {
  sku: string;
  name: string;
  price_cents: number;
}

/**
 * `name` and `unit_cents` are copied from catalog at purchase time.
 *
 * Not caching, and not denormalisation for speed — correctness. An order records what
 * was sold, and catalog is free to re-price tomorrow. It also happens to be what lets
 * `GET /v1/orders/{id}` answer without calling anybody: a dependency you do not have
 * cannot be down.
 */
export interface OrderLine {
  sku: string;
  name: string;
  unit_cents: number;
  qty: number;
}

export interface Payment {
  status: string;
  auth_code: string | null;
}

export interface Order {
  id: string;
  status: string;
  total_cents: number;
  created_at: string;
  lines: OrderLine[];
  payment: Payment | null;
}
