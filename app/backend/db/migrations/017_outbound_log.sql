-- Migration 017: Collapse outbound_tasks text fields into one markdown log,
-- replace state machine with a single closed_at flag, drop outbound_task_updates
-- and events. Atomic — all changes succeed or none.
--
-- Why:
--   * dispatch_prompt / customer_context / system_context were three text
--     slots overwritten on amendment. outbound_task_updates was a sidecar to
--     preserve the trail. Both collapse into `log` as agent-curated markdown.
--   * 7-state CHECK constraint + 90-min grace window solved a problem that
--     doesn't exist once share_update stops being terminal: tasks stay open
--     until something explicitly closes them.
--   * events / events_search were a search layer over multiparty audit;
--     redundant when the agent searches outbound_tasks.log directly.

BEGIN;

-- 1. Add new columns (NOT NULL log defaulted to '' so backfill writes do
--    nothing unsafe; closed_at nullable since open tasks have no value yet).
ALTER TABLE outbound_tasks
    ADD COLUMN IF NOT EXISTS log TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ NULL;

-- 2. Backfill closed_at from terminal-state rows.
--    'running' / 'queued' stay open (closed_at NULL).
--    'succeeded' / 'failed' / 'timed_out' / 'cancelled' / 'escalated' close
--    at their resolved_at (or dispatched_at as a last-resort floor).
UPDATE outbound_tasks
SET closed_at = COALESCE(resolved_at, dispatched_at)
WHERE state IN ('succeeded', 'failed', 'timed_out', 'cancelled', 'escalated')
  AND closed_at IS NULL;

-- 3. Backfill `log` by stitching dispatch_prompt + customer_context +
--    system_context + the trail in outbound_task_updates. Order: dispatch
--    section, then update history (oldest first), then a closing marker
--    when applicable. Each section is a markdown H2.
UPDATE outbound_tasks t
SET log = (
    -- ## Dispatched section — the original brief.
    '## Dispatched ' || to_char(t.dispatched_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SSZ') || E'\nBrief: ' ||
    COALESCE(NULLIF(t.dispatch_prompt, ''), '(no brief recorded)') ||
    -- Updates history (one section per outbound_task_updates row).
    COALESCE(
        (
            SELECT string_agg(
                E'\n\n## Update ' || to_char(u.created_at AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SSZ') ||
                CASE
                    WHEN u.customer_context IS NOT NULL AND u.customer_context <> ''
                    THEN E'\nRelayed to customer: ' || u.customer_context
                    ELSE ''
                END ||
                CASE
                    WHEN u.system_context IS NOT NULL AND u.system_context <> ''
                    THEN E'\nSystem note: ' || u.system_context
                    ELSE ''
                END,
                ''
                ORDER BY u.created_at
            )
            FROM outbound_task_updates u
            WHERE u.task_key = t.task_key
        ),
        ''
    ) ||
    -- If the row had a customer_context / system_context that's NOT in the
    -- updates table (early-era rows), include it as a final synthesized
    -- section so we don't lose the data.
    CASE
        WHEN t.customer_context IS NOT NULL AND t.customer_context <> '' AND NOT EXISTS (
            SELECT 1 FROM outbound_task_updates u
            WHERE u.task_key = t.task_key AND u.customer_context = t.customer_context
        )
        THEN E'\n\n## Relayed to customer ' ||
             to_char(COALESCE(t.resolved_at, t.dispatched_at) AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SSZ') || E'\n' || t.customer_context
        ELSE ''
    END ||
    CASE
        WHEN t.system_context IS NOT NULL AND t.system_context <> '' AND NOT EXISTS (
            SELECT 1 FROM outbound_task_updates u
            WHERE u.task_key = t.task_key AND u.system_context = t.system_context
        )
        THEN E'\n\n## System note ' ||
             to_char(COALESCE(t.resolved_at, t.dispatched_at) AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SSZ') || E'\n' || t.system_context
        ELSE ''
    END ||
    -- Final close marker for terminal-state rows.
    CASE t.state
        WHEN 'failed'    THEN E'\n\n## Closed (failed) ' ||
            to_char(COALESCE(t.resolved_at, t.dispatched_at) AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SSZ')
        WHEN 'timed_out' THEN E'\n\n## Closed (timeout) ' ||
            to_char(COALESCE(t.resolved_at, t.dispatched_at) AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SSZ')
        WHEN 'cancelled' THEN E'\n\n## Closed (cancelled) ' ||
            to_char(COALESCE(t.resolved_at, t.dispatched_at) AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SSZ')
        WHEN 'escalated' THEN E'\n\n## Escalated ' ||
            to_char(COALESCE(t.resolved_at, t.dispatched_at) AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SSZ')
        ELSE ''
    END
)
WHERE log = '';

-- 4. Drop the old text columns + state machine.
ALTER TABLE outbound_tasks
    DROP COLUMN IF EXISTS dispatch_prompt,
    DROP COLUMN IF EXISTS summary,
    DROP COLUMN IF EXISTS customer_context,
    DROP COLUMN IF EXISTS system_context,
    DROP COLUMN IF EXISTS state,
    DROP COLUMN IF EXISTS resolved_at;

-- 5. Index for the new manifest filter (open tasks per contact).
DROP INDEX IF EXISTS idx_outbound_tasks_customer_state;
DROP INDEX IF EXISTS idx_outbound_tasks_state_timeout;

CREATE INDEX IF NOT EXISTS idx_outbound_tasks_open_per_contact
    ON outbound_tasks (business_id, contact_id, dispatched_at DESC)
    WHERE closed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_outbound_tasks_open_per_customer
    ON outbound_tasks (business_id, customer_id, dispatched_at DESC)
    WHERE closed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_outbound_tasks_open_timeout
    ON outbound_tasks (timeout_at)
    WHERE closed_at IS NULL;

-- 6. Drop the now-redundant tables. CASCADE handles any lingering FKs.
DROP TABLE IF EXISTS outbound_task_updates CASCADE;
DROP TABLE IF EXISTS events CASCADE;

COMMIT;
