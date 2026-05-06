-- Migration 015: Outbound task updates (append-only history of share_update calls)
-- Each share_update call from the outbound agent appends a row here so vendor
-- corrections / amendments after the first resolution are preserved. The
-- outbound_tasks row keeps the latest customer_context/system_context for
-- quick reads; this table holds the trail.

CREATE TABLE IF NOT EXISTS outbound_task_updates (
    id BIGSERIAL PRIMARY KEY,
    task_key TEXT NOT NULL REFERENCES outbound_tasks(task_key) ON DELETE CASCADE,
    customer_context TEXT,
    system_context TEXT,
    content_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (task_key, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_outbound_task_updates_task_created
    ON outbound_task_updates (task_key, created_at);
