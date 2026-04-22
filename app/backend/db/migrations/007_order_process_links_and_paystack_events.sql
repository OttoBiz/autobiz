-- Authoritative Paystack charge.success rows (idempotent by reference) and order↔process linkage for Redis/DB alignment.

CREATE TABLE IF NOT EXISTS paystack_webhook_events (
    reference TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    amount_kobo BIGINT,
    currency TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paystack_webhook_events_user_created
    ON paystack_webhook_events(user_id, business_id, created_at DESC);

CREATE TABLE IF NOT EXISTS order_process_links (
    order_id UUID PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
    process_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    process_completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_order_process_links_user_business
    ON order_process_links(user_id, business_id);
