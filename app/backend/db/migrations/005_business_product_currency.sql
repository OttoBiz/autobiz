-- Default selling currency per business; products.currency NULL means inherit from business.

ALTER TABLE businesses
    ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'NGN';

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS currency TEXT;

UPDATE products SET currency = 'NGN' WHERE currency IS NULL;
