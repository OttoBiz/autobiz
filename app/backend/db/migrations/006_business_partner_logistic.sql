-- Preferred logistics partner (same businesses table; FK to a logistics row).
ALTER TABLE businesses
    ADD COLUMN IF NOT EXISTS partner_logistic_id UUID REFERENCES businesses (id);

CREATE INDEX IF NOT EXISTS idx_businesses_partner_logistic
    ON businesses (partner_logistic_id)
    WHERE partner_logistic_id IS NOT NULL;
