-- Create users table for better-auth integration
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_versions WHERE version = '001') THEN
        CREATE TABLE users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email VARCHAR(255) UNIQUE NOT NULL,
            name VARCHAR(255),
            avatar_url VARCHAR(500),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );

        CREATE INDEX idx_users_email ON users(email);

        INSERT INTO schema_versions (version, description)
        VALUES ('001', 'Create users table');

        RAISE NOTICE '✓ Schema 001 applied: Create users table';
    ELSE
        RAISE NOTICE 'Schema 001 already applied, skipping...';
    END IF;
END $$;
