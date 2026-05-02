-- Migration 012: Product floor price for negotiation
-- When is_negotiable = true, floor_price (if set) is the lowest price
-- the agent is allowed to accept. The agent negotiates above the floor
-- and never reveals it to the customer. NULL means no floor configured —
-- the agent must escalate to the vendor for terms.

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS floor_price DECIMAL(10, 2);

ALTER TABLE products
    ADD CONSTRAINT products_floor_price_below_price
    CHECK (floor_price IS NULL OR floor_price <= price);
