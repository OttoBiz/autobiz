-- Migration 020: Move payment instruments off `businesses` into a per-tenant
-- per-provider credentials table.
--
-- Why:
--   `businesses` was carrying provider-specific columns (bank_name,
--   bank_account_number, bank_account_name, paystack_public_key,
--   paystack_secret_key). Adding Flutterwave / Stripe / Mono / OPay would
--   mean another five `ALTER TABLE businesses ADD COLUMN ...` per provider.
--   Mirrors the channel_credentials shape from migration 018.
--
-- Shape:
--   One row per (business, provider). `credentials` is a JSONB bag whose
--   keys are provider-specific:
--     - bank_transfer: { bank_name, bank_account_number, bank_account_name }
--     - paystack:      { public_key, secret_key }
--     - future:        whatever the integration needs
--   `provider` stays TEXT (not enum) so adding a provider is a write,
--   not a migration.
--
-- Backfill:
--   - Every business with a bank_name + bank_account_number gets a
--     `bank_transfer` row. Rows with only partial bank info (one column
--     populated) are skipped — partial bank data is unusable to the agent
--     anyway, and a half-populated jsonb would hide the gap.
--   - Every business with both paystack keys gets a `paystack` row.
--
-- Drops are atomic with the backfill so a half-migrated state is
-- impossible.

BEGIN;

CREATE TABLE IF NOT EXISTS payment_credentials (
    business_id  UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    provider     TEXT NOT NULL,
    credentials  JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (business_id, provider)
);

-- Backfill bank_transfer rows. Skip incomplete bank info — both name and
-- account number are required for the agent to surface the details.
INSERT INTO payment_credentials (business_id, provider, credentials)
SELECT
    id,
    'bank_transfer',
    jsonb_strip_nulls(jsonb_build_object(
        'bank_name',           NULLIF(bank_name, ''),
        'bank_account_number', NULLIF(bank_account_number, ''),
        'bank_account_name',   NULLIF(bank_account_name, '')
    ))
FROM businesses
WHERE NULLIF(bank_name, '') IS NOT NULL
  AND NULLIF(bank_account_number, '') IS NOT NULL
ON CONFLICT (business_id, provider) DO NOTHING;

-- Backfill paystack rows. Both keys must be present — a public key alone
-- isn't actionable.
INSERT INTO payment_credentials (business_id, provider, credentials)
SELECT
    id,
    'paystack',
    jsonb_build_object(
        'public_key', paystack_public_key,
        'secret_key', paystack_secret_key
    )
FROM businesses
WHERE NULLIF(paystack_public_key, '') IS NOT NULL
  AND NULLIF(paystack_secret_key, '') IS NOT NULL
ON CONFLICT (business_id, provider) DO NOTHING;

ALTER TABLE businesses
    DROP COLUMN IF EXISTS bank_name,
    DROP COLUMN IF EXISTS bank_account_number,
    DROP COLUMN IF EXISTS bank_account_name,
    DROP COLUMN IF EXISTS paystack_public_key,
    DROP COLUMN IF EXISTS paystack_secret_key;

COMMIT;
