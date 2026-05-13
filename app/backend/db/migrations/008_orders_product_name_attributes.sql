-- Migration 008: First-class product snapshot on orders
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS product_name TEXT,
    ADD COLUMN IF NOT EXISTS product_attributes JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_orders_product_name ON orders (product_name)
    WHERE product_name IS NOT NULL;
