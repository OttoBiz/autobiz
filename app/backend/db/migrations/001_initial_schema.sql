-- Migration tracking table
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);

-- Business schema
CREATE TABLE businesses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    product_schema JSONB NOT NULL DEFAULT '{}', -- e.g., {"color": {"type": "string", "filterable": true}, "size": {"type": "string"}}
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Products schema
CREATE TABLE products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL,
    stock_quantity INTEGER DEFAULT 0,
    sku TEXT,
    category TEXT,
    attributes JSONB NOT NULL DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,

    -- Full-text search vector
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english',
            coalesce(name, '') || ' ' ||
            coalesce(description, '') || ' ' ||
            coalesce(category, '')
        )
    ) STORED,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_products_business ON products(business_id);
CREATE INDEX idx_products_category ON products(category);
CREATE INDEX idx_products_price ON products(price);
CREATE INDEX idx_products_active ON products(is_active);
CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_products_attributes ON products USING GIN (attributes);
CREATE INDEX idx_products_search ON products USING GIN (search_vector);

-- Helper view: Get available attributes per business with their usage
CREATE VIEW business_product_attributes AS
SELECT
    business_id,
    attribute_name,
    COUNT(*) AS product_count
FROM products,
LATERAL jsonb_object_keys(attributes) AS attribute_name
WHERE attributes != '{}'::jsonb
GROUP BY business_id, attribute_name;