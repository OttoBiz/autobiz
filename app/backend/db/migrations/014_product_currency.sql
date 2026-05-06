-- Migration 014: Product currency
-- Adds an explicit currency column so prices are no longer implicitly NGN.
-- Existing rows backfill to 'NGN' to match prior behaviour.

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'NGN';
