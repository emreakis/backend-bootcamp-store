-- =============================================================================
--  THE STORE — one schema, one file, one database.
-- =============================================================================
--
--  Every module's tables live here side by side. Nothing stops a query in one
--  module from reading another module's tables except the discipline we impose
--  in code. That is the monolith's bargain: total freedom now, no seams later.
--
--  Two lines below are marked "LOST BY SATURDAY". They are the foreign keys
--  that cross a module boundary. They cost nothing here and are impossible
--  once each module becomes a service with its own database. Find them, and
--  you have found the exercise.
--
--  Owner comments are not decoration. They are the only thing making this a
--  MODULAR monolith rather than a big ball of mud: a module reads and writes
--  the tables it owns, and reaches every other table through that module's
--  public API. Break that rule and Saturday's split stops being possible.
-- =============================================================================

PRAGMA foreign_keys = ON;

-- owned by: catalog ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    sku          TEXT    PRIMARY KEY,
    name         TEXT    NOT NULL,
    price_cents  INTEGER NOT NULL CHECK (price_cents >= 0),
    stock        INTEGER NOT NULL CHECK (stock >= 0)
);

-- owned by: orders -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    id           TEXT    PRIMARY KEY,
    status       TEXT    NOT NULL CHECK (status IN ('CONFIRMED', 'CANCELLED')),
    total_cents  INTEGER NOT NULL CHECK (total_cents >= 0),
    created_at   TEXT    NOT NULL
);

-- owned by: orders -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_lines (
    order_id     TEXT    NOT NULL,
    sku          TEXT    NOT NULL,
    -- name and unit_cents are COPIED from the product at purchase time. This is
    -- not denormalisation for speed, it is correctness: an order records what
    -- was sold, not what the catalog happens to say today. Re-price a product
    -- next week and every historical order must keep its old number.
    -- This copy is the part that survives Saturday.
    name         TEXT    NOT NULL,
    unit_cents   INTEGER NOT NULL CHECK (unit_cents >= 0),
    qty          INTEGER NOT NULL CHECK (qty > 0),

    PRIMARY KEY (order_id, sku),
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (sku)      REFERENCES products(sku)   -- <<< LOST BY SATURDAY
);

-- owned by: payments ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS payments (
    id            TEXT    PRIMARY KEY,
    order_id      TEXT    NOT NULL,
    amount_cents  INTEGER NOT NULL CHECK (amount_cents >= 0),
    status        TEXT    NOT NULL CHECK (status IN ('APPROVED', 'DECLINED')),
    auth_code     TEXT,
    created_at    TEXT    NOT NULL,

    FOREIGN KEY (order_id) REFERENCES orders(id)      -- <<< LOST BY SATURDAY
);

CREATE INDEX IF NOT EXISTS idx_order_lines_order ON order_lines (order_id);
CREATE INDEX IF NOT EXISTS idx_payments_order    ON payments (order_id);
