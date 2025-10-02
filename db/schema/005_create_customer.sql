-- Schema version 005: Create customer table

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_versions WHERE version = '005') THEN
        -- Create customer table
        CREATE TABLE customer (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,

            -- Basic Info
            name VARCHAR(255),
            email VARCHAR(255),
            phone VARCHAR(50),

            -- CRM fields
            tags TEXT[] DEFAULT '{}',
            segments TEXT[] DEFAULT '{}',
            lifecycle_stage VARCHAR(50),
            customer_value_score INTEGER,
            notes TEXT,

            -- Metadata
            custom_fields JSONB DEFAULT '{}',
            preferences JSONB DEFAULT '{}',

            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );

        -- Indexes for fast lookups within a business
        CREATE INDEX idx_customer_business_id ON customer(business_id);
        CREATE INDEX idx_customer_business_email ON customer(business_id, email);
        CREATE INDEX idx_customer_business_phone ON customer(business_id, phone);

        INSERT INTO schema_versions (version, description)
        VALUES ('005', 'Create customer table');

        RAISE NOTICE '✓ Schema 005 applied';
    ELSE
        RAISE NOTICE 'Schema 005 already applied, skipping...';
    END IF;
END $$;
