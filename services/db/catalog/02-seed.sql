-- The same eight products as the monolith, so a demo in services/ and a demo in
-- monolith/ produce the same numbers and the comparison is honest.
--
-- ROA-008 is still priced above the payment decline threshold. It is how you make a
-- charge fail on demand — and in the split system, watching a 402 come back with no
-- order written is the local-transaction half of the story still working.

INSERT INTO products (sku, name, price_cents, stock) VALUES
    ('ESP-001', 'Espresso Machine',       49900,  12),
    ('GRD-002', 'Burr Grinder',           18900,  30),
    ('KTL-003', 'Gooseneck Kettle',        7900,  45),
    ('SCL-004', 'Precision Scale',         4900,  60),
    ('BNS-005', 'Single Origin Beans',     1800, 500),
    ('FLT-006', 'Paper Filters',            900, 800),
    ('MUG-007', 'Ceramic Mug',             1500, 200),
    ('ROA-008', 'Home Coffee Roaster',   529900,   3)
ON CONFLICT (sku) DO NOTHING;
