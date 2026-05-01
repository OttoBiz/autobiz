-- Migration 007: Contacts address book + tenant owner identification +
-- outbound_tasks ledger refactor.
--
-- Three coupled changes that have to land together: outbound dispatch can't
-- work without a real address book, the inbound resolver can't tell tenant
-- owners apart from customers without owner_wa_id, and the ledger has to
-- point at contacts (not the literal "vendor"/"logistics" string the agent
-- used to pass).

-- 1. Tenants identify their own operator phone, so an inbound from that
--    wa_id isn't accidentally turned into a customer record.
ALTER TABLE businesses
    ADD COLUMN IF NOT EXISTS owner_wa_id TEXT;

-- 2. Address book. `role` is intentionally TEXT (not enum) so tenants can
--    file contacts under their own categories ("vendor", "logistics",
--    "tailor", "courier", whatever). `notes` is free-text capability hints
--    the agent reads when picking a contact ("ships Lagos same-day",
--    "specializes in ankara").
--
--    `channel_business_id` is per-contact override of the sender
--    phone_number_id. NULL means "use the tenant's default
--    whatsapp_phone_number_id" — almost always what we want.
CREATE TABLE IF NOT EXISTS contacts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id         UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    role                TEXT NOT NULL,
    channel             TEXT NOT NULL,
    channel_user_id     TEXT NOT NULL,
    channel_business_id TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (business_id, channel, channel_user_id)
);

-- Agent's "give me all logistics" lookup.
CREATE INDEX IF NOT EXISTS idx_contacts_business_role
    ON contacts (business_id, role);

-- 3. Outbound ledger refactor.
--    Drop the `party` text column outright — prod has no real history yet,
--    and keeping a dead column around as backwards-compat would just be a
--    footgun (someone reads it expecting it to mean something).
--
--    `contact_id` is the live pointer for routing. `contact_name` and
--    `contact_role` are denormalized snapshots so a deleted contact doesn't
--    break completed-task display or analytics. ON DELETE SET NULL on
--    contact_id matches that intent: history rows survive contact deletion.
ALTER TABLE outbound_tasks
    DROP COLUMN IF EXISTS party;

ALTER TABLE outbound_tasks
    ADD COLUMN IF NOT EXISTS contact_id UUID REFERENCES contacts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS contact_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS contact_role TEXT NOT NULL DEFAULT '';

-- Drop the defaults — required-at-insert is what we want; the empty-string
-- default was only there to satisfy NOT NULL on existing rows during the
-- ADD COLUMN. New inserts must supply real values.
ALTER TABLE outbound_tasks
    ALTER COLUMN contact_name DROP DEFAULT,
    ALTER COLUMN contact_role DROP DEFAULT;

-- Inbound contact-reply routing (deferred, but the index is cheap to add now
-- so we don't need a separate migration when we wire it).
CREATE INDEX IF NOT EXISTS idx_outbound_tasks_contact_state
    ON outbound_tasks (business_id, contact_id, state);
