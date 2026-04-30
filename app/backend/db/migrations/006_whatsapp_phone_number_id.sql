-- Adds the Meta-assigned WhatsApp `phone_number_id` to businesses so the
-- inbound webhook can resolve `metadata.phone_number_id` → tenant UUID.
-- The same value is reused on every outbound (it identifies the *sender*,
-- the business's WA Business number, not the recipient).

ALTER TABLE businesses
    ADD COLUMN IF NOT EXISTS whatsapp_phone_number_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_businesses_wa_phone_number_id
    ON businesses(whatsapp_phone_number_id)
    WHERE whatsapp_phone_number_id IS NOT NULL;
