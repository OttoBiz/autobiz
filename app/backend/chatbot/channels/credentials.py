"""Per-tenant per-channel credential lookups.

Backs the wire-level sender identity for outbound (`get_sender`) and the
tenant resolution for inbound (`resolve_tenant_by_sender`). Both paths used
to read `businesses.whatsapp_phone_number_id` directly; consolidating here
keeps channel-specific schema knowledge out of the agents and the
inbound resolver, and gives a single seam to extend when Slack / email /
SMS senders land.
"""

from __future__ import annotations

from uuid import UUID

from backend.db.connection import get_db


async def get_sender(business_id: UUID, channel: str) -> str | None:
    """Return the wire-level sender id for (tenant, channel), or None.

    For WhatsApp this is the Meta-assigned `phone_number_id` used as the
    POST target on outbound. None means the tenant has not configured a
    sender for this channel — caller decides whether to fall back or fail.
    """
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT channel_business_id
            FROM channel_credentials
            WHERE business_id = $1 AND channel = $2
            """,
            business_id,
            channel,
        )
    return row["channel_business_id"] if row else None


async def upsert(
    *,
    business_id: UUID,
    channel: str,
    channel_business_id: str,
    secrets: dict | None = None,
) -> None:
    """Insert-or-update one credential row. `secrets` is merged when given."""
    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO channel_credentials (
                business_id, channel, channel_business_id, secrets
            )
            VALUES ($1, $2, $3, COALESCE($4::jsonb, '{}'::jsonb))
            ON CONFLICT (business_id, channel) DO UPDATE SET
                channel_business_id = EXCLUDED.channel_business_id,
                secrets             = COALESCE(EXCLUDED.secrets, channel_credentials.secrets),
                updated_at          = NOW()
            """,
            business_id,
            channel,
            channel_business_id,
            secrets,
        )
