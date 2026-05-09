-- Migration 018: Move WhatsApp sender ID off `businesses` into a dedicated
-- per-channel credentials table.
--
-- Why:
--   `businesses.whatsapp_phone_number_id` baked one channel's wire format
--   into the tenant table. Adding Slack / email / SMS senders meant another
--   `ALTER TABLE businesses ADD COLUMN ..._id` each time. Channel concerns
--   belong in a channel-shaped table.
--
-- Shape:
--   One row per (business, channel). `channel_business_id` is the wire-level
--   sender identifier (Meta phone_number_id today; slack workspace id /
--   verified email / sender phone in future channels). `secrets` is a JSONB
--   bag for per-channel auth material that doesn't need its own column —
--   keeps Paystack-style sibling tables an option without blocking on them.
--
-- Lookup paths preserved:
--   - inbound resolver: `WHERE channel = 'whatsapp' AND channel_business_id = $1`
--     hits idx_channel_credentials_lookup (unique).
--   - outbound sender lookup: `WHERE business_id = $1 AND channel = $2` hits
--     the PK directly.
--
-- Backfill is unconditional: every existing row with a non-null
-- whatsapp_phone_number_id becomes a `whatsapp` credential row, then the
-- column and its unique index are dropped atomically with the rest.

BEGIN;

CREATE TABLE IF NOT EXISTS channel_credentials (
    business_id          UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    channel              TEXT NOT NULL,
    channel_business_id  TEXT NOT NULL,
    secrets              JSONB NOT NULL DEFAULT '{}',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (business_id, channel)
);

-- Inbound webhook lookup. Unique because two tenants cannot share the same
-- Meta phone_number_id; the same uniqueness held on the dropped index.
CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_credentials_lookup
    ON channel_credentials (channel, channel_business_id);

INSERT INTO channel_credentials (business_id, channel, channel_business_id)
SELECT id, 'whatsapp', whatsapp_phone_number_id
FROM businesses
WHERE whatsapp_phone_number_id IS NOT NULL
ON CONFLICT (business_id, channel) DO NOTHING;

DROP INDEX IF EXISTS idx_businesses_wa_phone_number_id;
ALTER TABLE businesses DROP COLUMN IF EXISTS whatsapp_phone_number_id;

COMMIT;
