"""Channel identity accessors.

One row per `(business_id, customer_id, channel)`. `last_inbound_at` tracks
the most recent inbound message on that channel and drives
`registry.get_for_customer` (the channel matching the customer's most
recent activity).
"""

from uuid import UUID

from backend.chatbot.channels import registry
from backend.chatbot.channels.base import Channel, ChannelIdentity
from backend.db.connection import get_db


_COLUMNS = "business_id, customer_id, channel, channel_user_id, last_inbound_at"


async def get_identity(
    business_id: UUID, customer_id: UUID, channel: str
) -> ChannelIdentity | None:
    pool = await get_db()
    query = f"""
        SELECT {_COLUMNS}
        FROM channel_identities
        WHERE business_id = $1 AND customer_id = $2 AND channel = $3
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, business_id, customer_id, channel)
    return _row_to_identity(row) if row else None


async def upsert_identity(identity: ChannelIdentity) -> None:
    pool = await get_db()
    query = """
        INSERT INTO channel_identities (
            business_id, customer_id, channel, channel_user_id, last_inbound_at
        )
        VALUES ($1::uuid, $2::uuid, $3, $4, $5)
        ON CONFLICT (business_id, customer_id, channel) DO UPDATE SET
            channel_user_id = EXCLUDED.channel_user_id,
            last_inbound_at = EXCLUDED.last_inbound_at
    """
    async with pool.acquire() as conn:
        await conn.execute(
            query,
            identity.business_id,
            identity.customer_id,
            identity.channel,
            identity.channel_user_id,
            identity.last_inbound_at,
        )


async def get_most_recent_identity(
    business_id: UUID, customer_id: UUID
) -> ChannelIdentity | None:
    pool = await get_db()
    query = f"""
        SELECT {_COLUMNS}
        FROM channel_identities
        WHERE business_id = $1 AND customer_id = $2
        ORDER BY last_inbound_at DESC NULLS LAST
        LIMIT 1
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, business_id, customer_id)
    return _row_to_identity(row) if row else None


def _row_to_identity(row) -> ChannelIdentity:
    return ChannelIdentity(
        business_id=str(row["business_id"]),
        customer_id=str(row["customer_id"]),
        channel=row["channel"],
        channel_user_id=row["channel_user_id"],
        last_inbound_at=row["last_inbound_at"],
    )


async def _resolve_channel_for_customer(
    business_id: str, customer_id: str
) -> Channel | None:
    identity = await get_most_recent_identity(UUID(business_id), UUID(customer_id))
    if identity is None:
        return None
    try:
        return registry.get(identity.channel)
    except KeyError:
        return None


registry.set_identity_resolver(_resolve_channel_for_customer)
