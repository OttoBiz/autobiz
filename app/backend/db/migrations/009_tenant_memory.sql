-- Migration 009: tenant-scoped agent memory.
--
-- Replaces the per-contact `contacts.agent_memory` (added in 008) with a
-- tenant-wide, file-system-shaped store. Mirrors the shape of Anthropic's
-- memory tool (`memory_20250818`): the agent organizes its own /memories
-- directory and reads from / writes to it on demand.
--
-- Why tenant-wide instead of per-contact:
-- - Memory the agent cares about cuts across partners ("we're closed
--   Sundays", "ankara prices are up 15% this quarter") more than it lives
--   inside one specific contact relationship.
-- - Both central (customer-facing) and outbound (vendor-facing) agents need
--   the same memory bucket — central might note something a vendor told us
--   that's relevant to customers; outbound might note something a customer
--   said that's relevant to a vendor.
-- - Per-contact buckets fragment the agent's worldview and bloat the prompt
--   when scoping is wrong.
--
-- "Path" is the agent-chosen file path inside /memories/. Hierarchy is
-- emergent from the path string — we don't model directories as rows.
-- A directory listing is a SELECT WHERE path LIKE '<prefix>/%'.

DROP INDEX IF EXISTS idx_contacts_business_role;  -- recreated below for clarity
ALTER TABLE contacts DROP COLUMN IF EXISTS agent_memory;
CREATE INDEX IF NOT EXISTS idx_contacts_business_role
    ON contacts (business_id, role);

CREATE TABLE IF NOT EXISTS tenant_memory (
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (business_id, path)
);

-- Prefix scans for `view <directory>` operations: "list every file under
-- /memories/vendors/" runs as `WHERE business_id = $1 AND path LIKE $2`.
-- The PK already supports this efficiently because (business_id, path) is
-- a btree, but an explicit index documents intent and lets the planner
-- pick it for path-only patterns if business_id ever moves.
CREATE INDEX IF NOT EXISTS idx_tenant_memory_path
    ON tenant_memory (business_id, path text_pattern_ops);
