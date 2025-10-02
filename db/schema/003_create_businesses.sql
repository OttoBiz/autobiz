-- Create businesses table
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_versions WHERE version = '003') THEN
        CREATE TABLE businesses (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255) NOT NULL,
            slug VARCHAR(255) UNIQUE NOT NULL,
            owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,

            -- Subscription
            subscription_plan_id UUID NOT NULL REFERENCES subscription_plans(id),
            subscription_status VARCHAR(50) NOT NULL DEFAULT 'trialing',
            current_period_end TIMESTAMP,
            trial_ends_at TIMESTAMP,

            -- Company Info
            description TEXT,
            industry VARCHAR(100),
            contact_email VARCHAR(255),
            phone VARCHAR(50),
            address TEXT,
            website VARCHAR(500),
            policies JSONB DEFAULT '{}',

            -- Branding
            logo_url VARCHAR(500),
            primary_color VARCHAR(7),
            theme_config JSONB DEFAULT '{}',

            -- Settings
            timezone VARCHAR(50) DEFAULT 'UTC',
            currency VARCHAR(3) DEFAULT 'USD',
            business_hours JSONB DEFAULT '{}',

            -- Product Catalog Sync
            catalog_sync_source VARCHAR(50),
            catalog_sync_config JSONB DEFAULT '{}',

            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );

        CREATE INDEX idx_businesses_slug ON businesses(slug);
        CREATE INDEX idx_businesses_owner_user_id ON businesses(owner_user_id);
        CREATE INDEX idx_businesses_subscription_status ON businesses(subscription_status);

        INSERT INTO schema_versions (version, description)
        VALUES ('003', 'Create businesses table');

        RAISE NOTICE '✓ Schema 003 applied: Create businesses table';
    ELSE
        RAISE NOTICE 'Schema 003 already applied, skipping...';
    END IF;
END $$;
