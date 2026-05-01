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
    agent_memory: str | None = None
    created_at: datetime
    updated_at: datetime


# Bound the agent's appended memory so it stays inside a sane prompt
# budget — Hermes-style. The agent must prioritize what's worth remembering;
# older notes get trimmed when the cap is reached.
AGENT_MEMORY_MAX_CHARS = 2500


_COLUMNS = (
    "id, business_id, name, role, channel, channel_user_id, "
    "channel_business_id, notes, agent_memory, created_at, updated_at"
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
        agent_memory=row["agent_memory"],
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


async def append_agent_memory(contact_id: UUID, note: str) -> str:
    """Append a markdown bullet to the contact's agent_memory journal.

    Bounded at AGENT_MEMORY_MAX_CHARS — when the new content would exceed
    that, oldest entries are trimmed from the front. Returns the post-write
    journal so callers can confirm what's now persisted.
    """
    bullet = f"- {note.strip()}\n"
    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT agent_memory FROM contacts WHERE id = $1 FOR UPDATE",
                contact_id,
            )
            if row is None:
                raise ValueError(f"unknown contact_id {contact_id}")
            existing = row["agent_memory"] or ""
            combined = existing + bullet
            if len(combined) > AGENT_MEMORY_MAX_CHARS:
                # Trim by full bullets from the front, not mid-line, so the
                # journal stays a valid markdown list.
                while len(combined) > AGENT_MEMORY_MAX_CHARS and "\n" in combined:
                    combined = combined.split("\n", 1)[1]
            await conn.execute(
                "UPDATE contacts SET agent_memory = $1, updated_at = NOW() WHERE id = $2",
                combined,
                contact_id,
            )
    return combined


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
