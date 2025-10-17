-- Schema version 010: Rename can_handoff_to to subagents

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_versions WHERE version = '010') THEN
    -- Rename the column
        ALTER TABLE agent RENAME COLUMN can_handoff_to TO subagents;

    -- Record schema version
        INSERT INTO schema_versions (version, description) 
        VALUES ('010', 'Rename can_handoff_to to subagents');

        RAISE NOTICE '✓ Schema 010 applied: Renamed can_handoff_to to subagents';
    ELSE
        RAISE NOTICE 'Schema 010 already applied, skipping ...';
    END IF;
END $$;
