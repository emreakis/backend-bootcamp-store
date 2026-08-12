-- =============================================================================
--  Seed data. Identical in all six implementations, so a demo in Go and a demo
--  in Ruby produce byte-for-byte the same responses.
-- =============================================================================
--
--  ROA-008 is deliberately priced above the payment decline threshold
--  (PAYMENT_DECLINE_OVER_CENTS, default 500000 = 5000.00). Ordering one of them
--  is the reproducible way to demonstrate a declined payment — and, more
--  importantly, to watch the whole checkout transaction roll back so that the
--  stock it had already reserved comes back.
--
--  On Saturday that rollback stops happening by itself. Remember this number.
-- =============================================================================

INSERT OR IGNORE INTO products (sku, name, price_cents, stock) VALUES
    ('ESP-001', 'Espresso Machine',       49900,  12),
    ('GRD-002', 'Burr Grinder',           18900,  30),
    ('KTL-003', 'Gooseneck Kettle',        7900,  45),
    ('SCL-004', 'Precision Scale',         4900,  60),
    ('BNS-005', 'Single Origin Beans',     1800, 500),
    ('FLT-006', 'Paper Filters',            900, 800),
    ('MUG-007', 'Ceramic Mug',             1500, 200),
    ('ROA-008', 'Home Coffee Roaster',   529900,   3);
