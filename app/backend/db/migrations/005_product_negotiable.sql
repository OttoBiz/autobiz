-- Migration 005: Product negotiation flag
-- Adds an explicit boolean for whether a product's price is open to
-- negotiation. The product agent answered "is this negotiable?" from
-- priors before this column existed, which led to confident-but-wrong
-- replies. With the field present the agent answers "no" when false
-- and escalates to vendor for the specific terms when true.

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS is_negotiable BOOLEAN NOT NULL DEFAULT FALSE;
