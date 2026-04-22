-- Migration 004: Channel identities
-- Maps a (business, customer) pair to one row per channel they use,
-- carrying the channel-native handle (phone, slack user id, email, ...)
-- and the timestamp of their last inbound message on that channel.
-- Used by the channel registry's `get_for_customer` to pick the channel
-- that matches the customer's most recent inbound activity.

CREATE TABLE IF NOT EXISTS channel_identities (
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel TEXT NOT NULL, -- 'whatsapp', 'slack', 'email', etc.
    channel_user_id TEXT NOT NULL, -- phone number, slack user id, email
    last_inbound_at TIMESTAMPTZ,
    PRIMARY KEY (business_id, customer_id, channel)
);

-- "Channel matching last inbound" lookup:
--   WHERE business_id=$1 AND customer_id=$2
--   ORDER BY last_inbound_at DESC NULLS LAST
--   LIMIT 1
-- The DESC NULLS LAST ordering on the index lets Postgres satisfy the
-- ORDER BY directly from the index without a sort step.
CREATE INDEX IF NOT EXISTS idx_channel_identities_last_inbound
    ON channel_identities (business_id, customer_id, last_inbound_at DESC NULLS LAST);
