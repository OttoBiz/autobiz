"""Per-tenant per-provider payment credentials.

Backs `central.get_business_payment_info` (today: bank_transfer) and any
future paystack / flutterwave / etc. integrations. Same pattern as
`backend.chatbot.channels.credentials`, but for payment providers.

`credentials` is a JSONB bag whose keys are provider-specific:
  - bank_transfer: { bank_name, bank_account_number, bank_account_name }
  - paystack:      { public_key, secret_key }
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from backend.db.connection import get_db


async def get(business_id: UUID, provider: str) -> dict[str, Any] | None:
    """Return the credentials blob for (tenant, provider), or None.

    None means the tenant has not configured that provider — caller decides
    whether to fall back, escalate, or return a "not configured" payload.
    """
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT credentials
            FROM payment_credentials
            WHERE business_id = $1 AND provider = $2
            """,
            business_id,
            provider,
        )
    if row is None:
        return None
    raw = row["credentials"]
    return raw if isinstance(raw, dict) else json.loads(raw)


async def upsert(
    *,
    business_id: UUID,
    provider: str,
    credentials: dict[str, Any],
) -> None:
    """Insert-or-replace one credentials row. Replaces the whole blob —
    callers that want to merge should read-modify-write."""
    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO payment_credentials (business_id, provider, credentials)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (business_id, provider) DO UPDATE SET
                credentials = EXCLUDED.credentials,
                updated_at  = NOW()
            """,
            business_id,
            provider,
            json.dumps(credentials),
        )
