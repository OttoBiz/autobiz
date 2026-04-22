-- Migration 003: Outbound task ledger
-- Append-only by identity: rows are never deleted, only `state` mutates.
-- One row per outbound task dispatched to a vendor/party.

CREATE TABLE IF NOT EXISTS outbound_tasks (
    task_key TEXT PRIMARY KEY,
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES users(id),
    party TEXT NOT NULL,
    initiated_by TEXT NOT NULL CHECK (initiated_by IN ('customer', 'system')),
    dispatch_prompt TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'timed_out', 'cancelled', 'escalated')) DEFAULT 'queued',
    customer_context TEXT,
    system_context TEXT,
    dispatched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    timeout_at TIMESTAMPTZ NOT NULL
);

-- Per-customer reads: pending tasks for a given customer in a business.
CREATE INDEX IF NOT EXISTS idx_outbound_tasks_customer_state
    ON outbound_tasks (business_id, customer_id, state);

-- Sweeper scan: find tasks past their timeout in non-terminal states.
CREATE INDEX IF NOT EXISTS idx_outbound_tasks_state_timeout
    ON outbound_tasks (state, timeout_at);
