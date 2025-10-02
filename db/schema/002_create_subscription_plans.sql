-- Create subscription_plans table
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_versions WHERE version = '002') THEN
        CREATE TABLE subscription_plans (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(100) NOT NULL,
            tier VARCHAR(50) NOT NULL UNIQUE,
            price_monthly DECIMAL(10, 2) NOT NULL,
            price_yearly DECIMAL(10, 2) NOT NULL,
            features JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );

        CREATE INDEX idx_subscription_plans_tier ON subscription_plans(tier);

        INSERT INTO schema_versions (version, description)
        VALUES ('002', 'Create subscription_plans table');

        RAISE NOTICE '✓ Schema 002 applied: Create subscription_plans table';
    ELSE
        RAISE NOTICE 'Schema 002 already applied, skipping...';
    END IF;
END $$;
