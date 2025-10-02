-- Schema version 006: Create conversation table

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_versions WHERE version = '006') THEN
        -- Create enum for conversation channel
        CREATE TYPE conversation_channel AS ENUM ('whatsapp', 'webchat', 'sms', 'email');

        -- Create enum for conversation status
        CREATE TYPE conversation_status AS ENUM ('active', 'resolved', 'escalated');

        -- Create conversation table
        CREATE TABLE conversation (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            customer_id UUID REFERENCES customer(id) ON DELETE SET NULL,
            business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,

            -- Channel & Status
            channel conversation_channel NOT NULL,
            status conversation_status DEFAULT 'active',

            -- Human-in-the-loop
            assigned_to_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            escalated_at TIMESTAMP,

            -- Training data
            feedback_score INTEGER,
            business_notes TEXT,

            -- Metadata
            metadata JSONB DEFAULT '{}',

            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );

        -- Indexes
        CREATE INDEX idx_conversation_customer_id ON conversation(customer_id);
        CREATE INDEX idx_conversation_business_id ON conversation(business_id);
        CREATE INDEX idx_conversation_assigned_to_user_id ON conversation(assigned_to_user_id);
        CREATE INDEX idx_conversation_status ON conversation(status);

        INSERT INTO schema_versions (version, description)
        VALUES ('006', 'Create conversation table');

        RAISE NOTICE '✓ Schema 006 applied';
    ELSE
        RAISE NOTICE 'Schema 006 already applied, skipping...';
    END IF;
END $$;
