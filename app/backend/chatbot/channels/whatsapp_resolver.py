"""Classify a WhatsApp inbound by tenant + sender in a single query.

The webhook receives Meta-native IDs (`phone_number_id`, `wa_id`); everything
below it is keyed by UUID. This module joins `businesses` against `contacts`
once to answer both axes at the same time: which tenant owns the receiving
number, and who the sender is relative to that tenant (owner / known contact /
otherwise a customer). Customer creation stays on its own helper so it only
fires on the customer branch.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from backend.db.connection import get_db


class InboundSender(BaseModel):
    """Discriminated result of resolving (receiver phone_number_id, sender wa_id)."""

    kind: Literal["unknown_tenant", "owner", "contact", "customer"]
    business_id: UUID | None = None      # set for owner | contact | customer
    contact_id: UUID | None = None       # set when kind == "contact"
    contact_name: str | None = None      # set when kind == "contact"
    contact_role: str | None = None      # set when kind == "contact"


async def resolve_inbound_sender(
    phone_number_id: str,
    wa_id: str,
) -> InboundSender:
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              b.id           AS business_id,
              b.owner_wa_id  AS owner_wa_id,
              c.id           AS contact_id,
              c.name         AS contact_name,
              c.role         AS contact_role
            FROM businesses b
            LEFT JOIN contacts c
              ON c.business_id     = b.id
             AND c.channel         = 'whatsapp'
             AND c.channel_user_id = $2
            WHERE b.whatsapp_phone_number_id = $1
            LIMIT 1
            """,
            phone_number_id,
            wa_id,
        )

    if row is None:
        return InboundSender(kind="unknown_tenant")
    if row["owner_wa_id"] == wa_id:
        return InboundSender(kind="owner", business_id=row["business_id"])
    if row["contact_id"] is not None:
        return InboundSender(
            kind="contact",
            business_id=row["business_id"],
            contact_id=row["contact_id"],
            contact_name=row["contact_name"],
            contact_role=row["contact_role"],
        )
    return InboundSender(kind="customer", business_id=row["business_id"])


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
