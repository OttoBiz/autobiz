-- Migration 011: Persist channel_business_id on channel_identities.
-- WhatsApp send needs the Meta phone_number_id (the tenant's sender) on
-- every outbound. The system-triggered path (orchestrator.wake_central →
-- _drain_and_reply) loads the customer's identity from this table; without
-- this column the loaded ChannelIdentity falls back to the internal tenant
-- UUID and Graph rejects the POST with "Object with ID '<uuid>' does not
-- exist". Storing channel_business_id closes that round-trip.

ALTER TABLE channel_identities
    ADD COLUMN IF NOT EXISTS channel_business_id TEXT;
