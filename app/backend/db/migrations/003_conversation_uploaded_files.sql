-- Persisted uploads: URL optional (local or S3), classification, searchable text.

CREATE TABLE IF NOT EXISTS conversation_uploaded_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    file_url TEXT,
    file_content_type TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    text_content TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversation_files_user_business
    ON conversation_uploaded_files (user_id, business_id, created_at DESC);
