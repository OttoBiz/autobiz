-- Schema version 008: Create product table

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_versions WHERE version = '008') THEN
        -- Create product table
        CREATE TABLE product (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,

            -- Product Info
            sku VARCHAR(100) NOT NULL,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            price DECIMAL(10, 2) NOT NULL,
            currency VARCHAR(3) DEFAULT 'USD',
            category VARCHAR(100),

            -- Inventory
            inventory_count INTEGER DEFAULT 0,
            low_stock_threshold INTEGER DEFAULT 10,

            -- Media & Variants
            images JSONB DEFAULT '[]',
            variants JSONB DEFAULT '{}',

            -- Metadata
            metadata JSONB DEFAULT '{}',
            status VARCHAR(50) DEFAULT 'active',

            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),

            -- Unique SKU per business
            CONSTRAINT unique_sku_per_business UNIQUE (business_id, sku)
        );

        -- Indexes
        CREATE INDEX idx_product_business_id ON product(business_id);
        CREATE INDEX idx_product_sku ON product(business_id, sku);
        CREATE INDEX idx_product_category ON product(category);
        CREATE INDEX idx_product_status ON product(status);

        INSERT INTO schema_versions (version, description)
        VALUES ('008', 'Create product table');

        RAISE NOTICE '✓ Schema 008 applied';
    ELSE
        RAISE NOTICE 'Schema 008 already applied, skipping...';
    END IF;
END $$;
