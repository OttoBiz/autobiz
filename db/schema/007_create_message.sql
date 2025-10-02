-- Schema version 007: Create message table

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_versions WHERE version = '007') THEN
        -- Create enum for message sender type
        CREATE TYPE message_sender_type AS ENUM ('customer', 'agent', 'user', 'system');

        -- Create message table
        CREATE TABLE message (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL REFERENCES conversation(id) ON DELETE RESTRICT,

            -- Sender
            sender_type message_sender_type NOT NULL,

            -- Content
            content TEXT NOT NULL,
            is_internal BOOLEAN DEFAULT FALSE,

            -- Metadata
            timestamp TIMESTAMP DEFAULT NOW()
        );

        -- Indexes
        CREATE INDEX idx_message_conversation_id ON message(conversation_id);
        CREATE INDEX idx_message_timestamp ON message(timestamp);
        CREATE INDEX idx_message_is_internal ON message(is_internal);

        INSERT INTO schema_versions (version, description)
        VALUES ('007', 'Create message table');

        RAISE NOTICE '✓ Schema 007 applied';
    ELSE
        RAISE NOTICE 'Schema 007 already applied, skipping...';
    END IF;
END $$;
