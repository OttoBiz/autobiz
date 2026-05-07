-- Migration 016: Multiparty event ledger
-- Append-only log of every party-crossing message in the system. The agent
-- searches it (via bm25s in-process) to retrieve context about a customer
-- across vendor / customer / business turns, replacing static deps-loaded
-- manifests as the source of truth for "what's happening with whom".
--
-- One row per multiparty message:
--   - customer→business (inbound DM)
--   - business→customer (agent reply, surfaced system_event)
--   - business→contact (outbound dispatch text, vendor follow-ups)
--   - contact→business (vendor inbound reply)
--
-- Internal state writes (tool calls, ledger mutations, hooks) do NOT log
-- here — those belong in domain-specific tables (outbound_tasks, etc).
--
-- customer_id is nullable: a vendor-initiated unprompted message has no
-- customer attached at write time; the agent's search resolves it later
-- by content + asks for confirmation when ambiguous. tenant scoping is
-- always business_id.

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    customer_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    contact_id UUID NULL REFERENCES contacts(id) ON DELETE SET NULL,
    task_key TEXT NULL REFERENCES outbound_tasks(task_key) ON DELETE SET NULL,
    thread_id TEXT NOT NULL,
    actor TEXT NOT NULL CHECK (actor IN ('customer', 'contact', 'business')),
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    content TEXT NOT NULL,
    provider_message_id TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Per-customer recent-events scan: powers cluster expansion in find_customer_context.
CREATE INDEX IF NOT EXISTS idx_events_business_customer_created
    ON events (business_id, customer_id, created_at DESC);

-- Per-contact recent-events scan: vendor-side history reads.
CREATE INDEX IF NOT EXISTS idx_events_business_contact_created
    ON events (business_id, contact_id, created_at DESC);

-- Tenant-wide scan: bm25s index rebuild over the last N days for one business.
CREATE INDEX IF NOT EXISTS idx_events_business_created
    ON events (business_id, created_at DESC);

-- Reply-id lookup: when a webhook carries context.id we resolve to task_key.
CREATE INDEX IF NOT EXISTS idx_events_provider_message_id
    ON events (provider_message_id)
    WHERE provider_message_id IS NOT NULL;
