-- Initialize schema tracking table
CREATE TABLE IF NOT EXISTS schema_versions (
    version VARCHAR(50) PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMP DEFAULT NOW()
);

-- Mark this schema as applied
INSERT INTO schema_versions (version, description)
VALUES ('000', 'Initialize schema tracking')
ON CONFLICT (version) DO NOTHING;
