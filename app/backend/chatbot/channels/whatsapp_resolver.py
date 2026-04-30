"""Translate WhatsApp-native identifiers (phone_number_id, wa_id) to internal UUIDs.

The webhook sees phone numbers; everything below it (AgentDeps, chat history,
inbox keys, channel_identities FK) is keyed by UUID. This module is the seam.

- `resolve_business_by_wa_phone_id` looks up the tenant whose Meta-assigned
  `phone_number_id` matches the inbound `metadata.phone_number_id`.
- `resolve_or_create_customer_by_phone` looks up (or inserts) the customer by
  their `wa_id` (their phone number, no `+` prefix per Meta's format).

Both are scoped to WhatsApp; other channels keep their own resolvers if/when
they need them.
"""

from __future__ import annotations

from uuid import UUID

from backend.chatbot.channels.base import ChannelIdentity, InboundMessage
from backend.db.connection import get_db


class UnknownWhatsAppBusiness(Exception):
    """Raised when an inbound webhook references a phone_number_id we don't own."""


async def resolve_business_by_wa_phone_id(phone_number_id: str) -> UUID:
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM businesses WHERE whatsapp_phone_number_id = $1",
            phone_number_id,
        )
    if row is None:
        raise UnknownWhatsAppBusiness(
            f"No business mapped to whatsapp phone_number_id={phone_number_id}"
        )
    return row["id"]


async def resolve_or_create_customer_by_phone(wa_id: str) -> UUID:
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE phone_number = $1", wa_id
        )
        if row is not None:
            return row["id"]
        row = await conn.fetchrow(
            """
            INSERT INTO users (phone_number)
            VALUES ($1)
            ON CONFLICT (phone_number) DO UPDATE SET phone_number = EXCLUDED.phone_number
            RETURNING id
            """,
            wa_id,
        )
    return row["id"]


async def resolve_inbound(msg: InboundMessage) -> InboundMessage:
    """Swap WA-native IDs in `msg.identity` for internal UUIDs.

    `WhatsappChannel.parse_inbound` builds an identity holding the raw Meta
    `phone_number_id` and `wa_id` in `business_id`/`customer_id`. This call
    looks up (or creates) the matching DB rows and returns a copy of the
    message whose identity is keyed by UUID, ready for the orchestrator.
    """
    raw_phone_number_id = msg.identity.channel_business_id or msg.identity.business_id
    raw_wa_id = msg.identity.channel_user_id

    business_uuid = await resolve_business_by_wa_phone_id(raw_phone_number_id)
    customer_uuid = await resolve_or_create_customer_by_phone(raw_wa_id)

    resolved_identity = ChannelIdentity(
        business_id=str(business_uuid),
        customer_id=str(customer_uuid),
        channel=msg.identity.channel,
        channel_user_id=raw_wa_id,
        channel_business_id=raw_phone_number_id,
        last_inbound_at=msg.identity.last_inbound_at,
    )
    return msg.model_copy(update={"identity": resolved_identity})
