-- Schema version 010: Update agent table for multi-agent system
--
-- Changes:
-- 1. Remove UNIQUE constraint on business_id (allow multiple agents per business)
-- 2. Add key field for agent routing (system identifier)
-- 3. Add tool_groups for toolset composition
-- 4. Add can_handoff_to for collaboration control
-- 5. Consolidate optional fields (personality, tone, greeting_message, avatar_url) into metadata
-- 6. Add new indexes for multi-agent lookups

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_versions WHERE version = '010') THEN

        -- Step 1: Drop the UNIQUE constraint on business_id
        ALTER TABLE agent DROP CONSTRAINT IF EXISTS agent_business_id_key;

        -- Step 2: Add new required fields with default values
        ALTER TABLE agent ADD COLUMN IF NOT EXISTS key VARCHAR(100);
        ALTER TABLE agent ADD COLUMN IF NOT EXISTS tool_groups JSONB DEFAULT '[]'::jsonb;
        ALTER TABLE agent ADD COLUMN IF NOT EXISTS can_handoff_to JSONB DEFAULT '[]'::jsonb;

        -- Step 3: Add metadata JSONB if it doesn't exist
        ALTER TABLE agent ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

        -- Step 4: Migrate existing data
        -- For existing agents, set default key and migrate optional fields to metadata
        UPDATE agent
        SET
            key = COALESCE(key, 'default'),
            tool_groups = COALESCE(tool_groups, '["catalog", "customers", "conversations", "collab"]'::jsonb),
            can_handoff_to = COALESCE(can_handoff_to, '[]'::jsonb),
            metadata = jsonb_build_object(
                'personality', personality,
                'tone', tone,
                'greeting_message', greeting_message,
                'avatar_url', avatar_url,
                'conversation_rules', COALESCE(conversation_rules, '{}'::jsonb)
            )
        WHERE key IS NULL;

        -- Step 5: Make key NOT NULL after setting defaults
        ALTER TABLE agent ALTER COLUMN key SET NOT NULL;

        -- Step 6: Drop old columns that are now in metadata
        ALTER TABLE agent DROP COLUMN IF EXISTS personality;
        ALTER TABLE agent DROP COLUMN IF EXISTS tone;
        ALTER TABLE agent DROP COLUMN IF EXISTS greeting_message;
        ALTER TABLE agent DROP COLUMN IF EXISTS avatar_url;
        ALTER TABLE agent DROP COLUMN IF EXISTS conversation_rules;

        -- Step 7: Add new indexes for multi-agent lookups
        -- Fast lookup by business and key (most common query)
        CREATE INDEX IF NOT EXISTS idx_agent_business_key
            ON agent(business_id, key);

        -- Active agents only (for filtering)
        CREATE INDEX IF NOT EXISTS idx_agent_active
            ON agent(status) WHERE status = 'active';

        -- Drop old business_id index if it exists (replaced by composite index)
        DROP INDEX IF EXISTS idx_agent_business_id;

        -- Step 8: Add unique constraint on (business_id, key) to prevent duplicate keys per business
        ALTER TABLE agent ADD CONSTRAINT unique_business_key
            UNIQUE (business_id, key);

        -- Record schema version
        INSERT INTO schema_versions (version, description)
        VALUES ('010', 'Update agent table for multi-agent system');

        RAISE NOTICE '✓ Schema 010 applied: agent table updated for multi-agent system';
    ELSE
        RAISE NOTICE 'Schema 010 already applied, skipping...';
    END IF;
END $$;