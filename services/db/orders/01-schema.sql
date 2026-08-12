-- =============================================================================
--  ORDERS' database. Orders' alone.
-- =============================================================================
--
--  This is where the bill from Session 1 comes due. Open db/schema.sql next to it
--  and find the two lines marked "LOST BY SATURDAY". Both are gone, and what
--  replaced them is written out below.
-- =============================================================================

CREATE TABLE IF NOT EXISTS orders (
    id           UUID        PRIMARY KEY,
    status       TEXT        NOT NULL CHECK (status IN ('CONFIRMED', 'CANCELLED')),
    total_cents  BIGINT      NOT NULL CHECK (total_cents >= 0),
    created_at   TIMESTAMPTZ NOT NULL,

    -- The payment outcome, copied here at checkout.
    --
    -- The payments service owns no database at all — it fronts a card provider and
    -- keeps nothing. So the only durable record that this order was paid for is the
    -- one orders writes down, in the same local transaction that writes the order.
    --
    -- There is a second reason, and it is the better one: GET /v1/orders/{id} has to
    -- answer without calling anybody. If rendering an order required a round trip to
    -- payments, then payments being down would take order history down with it. A
    -- dependency you do not have cannot be unavailable.
    payment_status    TEXT CHECK (payment_status IN ('APPROVED', 'DECLINED')),
    payment_auth_code TEXT
);

CREATE TABLE IF NOT EXISTS order_lines (
    order_id     UUID   NOT NULL REFERENCES orders(id),

    -- <<< THIS IS THE FOREIGN KEY THAT DIED.
    --
    -- In the monolith this column read:
    --     FOREIGN KEY (sku) REFERENCES products(sku)
    -- and the database refused to record a sale of a product that did not exist.
    --
    -- `products` now lives in a different database, in a different container, owned
    -- by a different service. There is no constraint that can span them. What
    -- enforced this for free is now a REST call in the checkout path, made before
    -- the insert, whose failure orders has to translate into a designed 404 — and
    -- which can time out, which the database never could.
    --
    -- You did not remove a foreign key. You replaced a guarantee with a request.
    sku          TEXT   NOT NULL,

    -- These two were a defensible optimisation in the monolith. Here they are the
    -- only copy there is: nothing in this database can join to a product name, and
    -- catalog is free to re-price tomorrow. An order records what was sold.
    name         TEXT   NOT NULL,
    unit_cents   BIGINT NOT NULL CHECK (unit_cents >= 0),
    qty          BIGINT NOT NULL CHECK (qty > 0),

    PRIMARY KEY (order_id, sku)
);

-- =============================================================================
--  The table the monolith did not need.
-- =============================================================================
--
--  In one process, a caller either got its answer or got an exception. There was no
--  third outcome, so POST /v1/orders needed no protection against being asked twice.
--
--  Across a network there is a third outcome: the order was created and the response
--  was lost. The caller cannot tell that apart from the order never existing, so a
--  well-behaved client retries — and without this table, retrying bills the customer
--  again.
--
--  Session 1 asked what you have to build that you do not need today. This table is
--  one of the answers, and it is also the reason orders is allowed to retry its own
--  call to payments: that hop carries an idempotency key for exactly the same reason.
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key          TEXT        PRIMARY KEY,
    order_id     UUID        NOT NULL REFERENCES orders(id),
    created_at   TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_order_lines_order ON order_lines (order_id);
