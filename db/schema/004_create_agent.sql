-- Schema version 004: Create agent table

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_versions WHERE version = '004') THEN
        -- Create agent table
        CREATE TABLE agent (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            business_id UUID NOT NULL UNIQUE REFERENCES businesses(id) ON DELETE CASCADE,

            -- Profile
            name VARCHAR(255) NOT NULL,
            avatar_url VARCHAR(500),
            personality TEXT,
            tone VARCHAR(100),

            -- System Prompt & Behavior
            system_prompt TEXT NOT NULL,
            greeting_message TEXT,
            conversation_rules JSONB DEFAULT '{}',

            -- Channels
            channels JSONB DEFAULT '{
                "whatsapp": {"enabled": false, "credentials": {}, "config": {}},
                "webchat": {"enabled": false, "config": {}},
                "sms": {"enabled": false, "credentials": {}, "config": {}},
                "email": {"enabled": false, "credentials": {}, "config": {}}
            }',

            -- Metadata
            status VARCHAR(50) DEFAULT 'active',
            version INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );

        -- Index for business lookup
        CREATE INDEX idx_agent_business_id ON agent(business_id);

        INSERT INTO schema_versions (version, description)
        VALUES ('004', 'Create agent table');

        RAISE NOTICE '✓ Schema 004 applied';
    ELSE
        RAISE NOTICE 'Schema 004 already applied, skipping...';
    END IF;
END $$;
