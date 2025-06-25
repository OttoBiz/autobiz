-- Initial PostgreSQL setup for WhatsApp AI Assistant
-- This script runs when the PostgreSQL container starts for the first time

-- Enable useful PostgreSQL extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Set timezone to UTC for consistent timestamps
SET timezone = 'UTC';

-- Log successful initialization
DO $$
BEGIN
    RAISE NOTICE 'WhatsApp AI Assistant PostgreSQL initialized successfully';
    RAISE NOTICE 'Extensions enabled: uuid-ossp, pg_trgm';
    RAISE NOTICE 'Timezone set to UTC';
    RAISE NOTICE 'Ready for application table creation via db_setup.py';
END
$$;
