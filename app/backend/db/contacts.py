"""Contacts address book accessors.

One row per (business_id, channel, channel_user_id) — the unique constraint
means a given partner phone can only be in a tenant's book once per channel.

`role` is free-text (not an enum) so tenants can categorize contacts however
fits their business. The agent reads `name`, `role`, and `notes` when
deciding which contact to dispatch to.

Read paths:
- `get_by_id`           : outbound dispatch resolves contact_id → identity
- `get_by_wa_id`        : webhook resolver checks "is this sender a contact?"
- `list_by_business`    : agent's address-book lookup tool

Write path:
- `upsert`              : seeder + (future) admin UI; idempotent on
                          (business_id, channel, channel_user_id)
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from backend.db.connection import get_db


class Contact(BaseModel):
    id: UUID
    business_id: UUID
    name: str
    role: str
    channel: str
    channel_user_id: str
    channel_business_id: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


_COLUMNS = (
    "id, business_id, name, role, channel, channel_user_id, "
    "channel_business_id, notes, created_at, updated_at"
)


def _row_to_contact(row) -> Contact:
    return Contact(
        id=row["id"],
        business_id=row["business_id"],
        name=row["name"],
        role=row["role"],
        channel=row["channel"],
        channel_user_id=row["channel_user_id"],
        channel_business_id=row["channel_business_id"],
        notes=row["notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def get_by_id(contact_id: UUID) -> Contact | None:
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_COLUMNS} FROM contacts WHERE id = $1", contact_id
        )
    return _row_to_contact(row) if row else None


async def get_by_wa_id(business_id: UUID, wa_id: str) -> Contact | None:
    """Find a tenant's contact by WhatsApp wa_id.

    Tenant-scoped on purpose: the same wa_id might be a contact for tenant A
    and a customer for tenant B. Always look up inside the right tenant.
    """
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT {_COLUMNS} FROM contacts
            WHERE business_id = $1 AND channel = 'whatsapp' AND channel_user_id = $2
            """,
            business_id,
            wa_id,
        )
    return _row_to_contact(row) if row else None


async def list_by_business(
    business_id: UUID, role: str | None = None
) -> list[Contact]:
    """Address-book lookup for the agent. Optionally filter by role."""
    pool = await get_db()
    async with pool.acquire() as conn:
        if role is None:
            rows = await conn.fetch(
                f"SELECT {_COLUMNS} FROM contacts WHERE business_id = $1 ORDER BY name",
                business_id,
            )
        else:
            rows = await conn.fetch(
                f"""
                SELECT {_COLUMNS} FROM contacts
                WHERE business_id = $1 AND role = $2
                ORDER BY name
                """,
                business_id,
                role,
            )
    return [_row_to_contact(r) for r in rows]


async def upsert(
    *,
    business_id: UUID,
    name: str,
    role: str,
    channel: str,
    channel_user_id: str,
    channel_business_id: str | None = None,
    notes: str | None = None,
) -> Contact:
    """Idempotent insert keyed on (business_id, channel, channel_user_id).

    Re-running with the same triple updates name/role/notes/channel_business_id
    in place — convenient for the env-driven seeder which runs every deploy.
    """
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            INSERT INTO contacts (
                business_id, name, role, channel, channel_user_id,
                channel_business_id, notes
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (business_id, channel, channel_user_id) DO UPDATE SET
                name = EXCLUDED.name,
                role = EXCLUDED.role,
                channel_business_id = EXCLUDED.channel_business_id,
                notes = EXCLUDED.notes,
                updated_at = NOW()
            RETURNING {_COLUMNS}
            """,
            business_id,
            name,
            role,
            channel,
            channel_user_id,
            channel_business_id,
            notes,
        )
    return _row_to_contact(row)
