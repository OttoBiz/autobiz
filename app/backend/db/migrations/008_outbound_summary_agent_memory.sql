-- Migration 008: outbound task summary + contact agent memory.
--
-- Two changes that support the multi-task contact-reply model:
--
-- 1. outbound_tasks.summary — one-line headline captured at dispatch time.
--    The outbound agent's manifest of open tasks for a contact would balloon
--    if it had to carry full dispatch_prompts, so we store a short summary
--    that fits inside the agent's context budget at dispatch time.
--
-- 2. contacts.agent_memory — Hermes-style curated notes the agent appends
--    via record_note(). Bounded long-text, durable across redeploys.
--    Loaded as prompt prefix on every contact run so the agent stays
--    consistent ("Adamu prefers voice notes", "DHL only delivers Mon/Wed").

ALTER TABLE outbound_tasks
    ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT '';

-- Drop the default — required-at-insert is what we want; the empty-string
-- default was only there to satisfy NOT NULL on existing rows during ADD.
ALTER TABLE outbound_tasks
    ALTER COLUMN summary DROP DEFAULT;

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS agent_memory TEXT;
