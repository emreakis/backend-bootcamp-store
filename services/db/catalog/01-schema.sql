-- =============================================================================
--  CATALOG's database. Catalog's alone.
-- =============================================================================
--
--  Compare this file with db/schema.sql, the monolith's single schema. That one had
--  four tables and two foreign keys crossing module boundaries. This one has one
--  table, and there is nothing here for a foreign key to point at.
--
--  "Database per service" is not a deployment detail — it is the boundary. Share a
--  database between two services and you have not built two services; you have built
--  one service with two front doors and a shared schema that neither team can change
--  alone. The physical separation is what makes the independence real.
--
--  Nothing outside this container has the credentials, and nothing outside the
--  catalog service should ever want them.
-- =============================================================================

CREATE TABLE IF NOT EXISTS products (
    sku          TEXT   PRIMARY KEY,
    name         TEXT   NOT NULL,
    price_cents  BIGINT NOT NULL CHECK (price_cents >= 0),

    -- Still here, still reported over the API, and now nothing ever decrements it.
    --
    -- In the monolith, checkout took stock off this shelf inside the same
    -- transaction that wrote the order. That transaction cannot span two databases,
    -- so the split system stopped trying: catalog is read-only and orders never
    -- touches this column.
    --
    -- That is the honest first answer to a distributed transaction — remove the
    -- need for one. Putting inventory back means a saga, a compensating release that
    -- survives a crash between two calls, and reservations that expire when no
    -- confirmation arrives. A module's worth of machinery to replace one ROLLBACK.
    stock        BIGINT NOT NULL CHECK (stock >= 0)
);
