-- Migration 010: collapse businesses.phone_number + owner_wa_id.
--
-- The two columns held redundant information once contacts + the inbound
-- resolver landed:
--   * owner_wa_id (added in 007) — operator's personal wa_id, used by the
--     resolver to detect "owner self-message" inbound webhooks.
--   * phone_number (added in 002) — display field, never read for messaging.
--
-- The tenant business has exactly one operationally meaningful phone
-- number: the operator's WhatsApp. Drop the legacy display field, rename
-- owner_wa_id to phone_number, and treat the column as wa_id format
-- (digits only, no leading +). Any caller still rendering it as "the
-- business phone" gets the operator's wa_id — accurate, just without
-- the + prefix the old display value had.

-- Stash the existing index on the legacy column so we can drop it
-- without leaving a dangling reference.
DROP INDEX IF EXISTS idx_businesses_phone;

ALTER TABLE businesses DROP COLUMN IF EXISTS phone_number;
ALTER TABLE businesses RENAME COLUMN owner_wa_id TO phone_number;

-- Re-create the index under the new column. The resolver does an exact
-- equality match (`phone_number = $2`) so a btree on it speeds the
-- inbound webhook hot path.
CREATE INDEX IF NOT EXISTS idx_businesses_phone_number
    ON businesses (phone_number);
