CREATE TABLE IF NOT EXISTS chat_history_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    business_id UUID NOT NULL,
    summary TEXT NOT NULL,
    messages_summarized INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_summary_pair ON chat_history_summaries (user_id, business_id);
