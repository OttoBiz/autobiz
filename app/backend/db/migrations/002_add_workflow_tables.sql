-- Migration 002: Add workflow tables for agent system
-- Adds: users, orders, transactions tables and enhances businesses table

-- Enhance businesses table with tier, payment, and social media fields
ALTER TABLE businesses
    ADD COLUMN IF NOT EXISTS business_type TEXT DEFAULT 'vendor',
    ADD COLUMN IF NOT EXISTS tier TEXT DEFAULT 'free',
    ADD COLUMN IF NOT EXISTS phone_number TEXT,
    ADD COLUMN IF NOT EXISTS email TEXT,
    ADD COLUMN IF NOT EXISTS ig_page TEXT,
    ADD COLUMN IF NOT EXISTS facebook_page TEXT,
    ADD COLUMN IF NOT EXISTS twitter_page TEXT,
    ADD COLUMN IF NOT EXISTS tiktok TEXT,
    ADD COLUMN IF NOT EXISTS bank_name TEXT,
    ADD COLUMN IF NOT EXISTS bank_account_number TEXT,
    ADD COLUMN IF NOT EXISTS bank_account_name TEXT,
    ADD COLUMN IF NOT EXISTS paystack_public_key TEXT,
    ADD COLUMN IF NOT EXISTS paystack_secret_key TEXT,
    ADD COLUMN IF NOT EXISTS human_agent_phone TEXT,
    ADD COLUMN IF NOT EXISTS human_agent_email TEXT;

-- Indexes for businesses table
CREATE INDEX IF NOT EXISTS idx_businesses_tier ON businesses(tier);
CREATE INDEX IF NOT EXISTS idx_businesses_type ON businesses(business_type);
CREATE INDEX IF NOT EXISTS idx_businesses_phone ON businesses(phone_number);
CREATE INDEX IF NOT EXISTS idx_businesses_ig ON businesses(ig_page);

-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number TEXT NOT NULL UNIQUE,
    full_name TEXT,
    delivery_address TEXT,
    city TEXT,
    state TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone_number);

-- Create orders table
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_number TEXT NOT NULL UNIQUE,
    user_id UUID NOT NULL REFERENCES users(id),
    business_id UUID NOT NULL REFERENCES businesses(id),
    logistic_id UUID REFERENCES businesses(id),
    status TEXT NOT NULL DEFAULT 'pending',
    total_amount DECIMAL(10,2) NOT NULL,
    delivery_address TEXT,
    delivery_city TEXT,
    delivery_state TEXT,
    tracking_number TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_business ON orders(business_id);
CREATE INDEX IF NOT EXISTS idx_orders_logistic ON orders(logistic_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_number ON orders(order_number);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at DESC);

-- Create transactions table
CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID REFERENCES orders(id),
    user_id UUID NOT NULL REFERENCES users(id),
    business_id UUID NOT NULL REFERENCES businesses(id),
    status TEXT NOT NULL DEFAULT 'pending',
    amount DECIMAL(10,2) NOT NULL,
    payment_method TEXT,
    receipt_image_url TEXT,
    transaction_reference TEXT,
    bank_name TEXT,
    account_number TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    verified_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_transactions_order ON transactions(order_id);
CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_business ON transactions(business_id);
CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status);
CREATE INDEX IF NOT EXISTS idx_transactions_created ON transactions(created_at DESC);
