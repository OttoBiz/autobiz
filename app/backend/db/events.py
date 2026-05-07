"""Multiparty event ledger — append-only log of every party-crossing message.

The agent uses this through `events_search.find_customer_clusters(...)` to
retrieve context across customer / contact / business turns, replacing the
static deps-loaded manifest as the source of truth for "what's happening
with whom for whom".

Hook points (multiparty boundaries — see migration 016):
  - inbound customer DM   → log_inbound (actor='customer', direction='in')
  - inbound vendor reply  → log_inbound (actor='contact', direction='in')
  - business → customer   → log_outbound (actor='business', direction='out')
  - business → contact    → log_outbound (actor='business', direction='out')

Internal state mutations (tool calls, outbound_task_updates, share_update
hook results) do NOT log here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from backend.db.connection import get_db


Actor = Literal["customer", "contact", "business"]
Direction = Literal["in", "out"]


class EventRow(BaseModel):
    id: int
    business_id: UUID
    customer_id: UUID | None
    contact_id: UUID | None
    task_key: str | None
    thread_id: str
    actor: Actor
    direction: Direction
    content: str
    provider_message_id: str | None
    created_at: datetime


_COLUMNS = (
    "id, business_id, customer_id, contact_id, task_key, thread_id, "
    "actor, direction, content, provider_message_id, created_at"
)


async def insert_event(
    *,
    business_id: UUID,
    actor: Actor,
    direction: Direction,
    thread_id: str,
    content: str,
    customer_id: UUID | None = None,
    contact_id: UUID | None = None,
    task_key: str | None = None,
    provider_message_id: str | None = None,
) -> int:
    """Insert one event row. Returns the new id.

    `content` is what the search index reads; pass the raw message text. Empty
    or whitespace-only content is rejected — the ledger should never grow rows
    that contribute nothing to retrieval.
    """
    if not content or not content.strip():
        raise ValueError("event content must be non-empty")

    pool = await get_db()
    query = """
        INSERT INTO events (
            business_id, customer_id, contact_id, task_key, thread_id,
            actor, direction, content, provider_message_id
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            query,
            business_id,
            customer_id,
            contact_id,
            task_key,
            thread_id,
            actor,
            direction,
            content,
            provider_message_id,
        )
    return int(row["id"])


async def list_recent_for_business(
    business_id: UUID,
    *,
    since: datetime | None = None,
    limit: int = 5000,
) -> list[EventRow]:
    """All recent events for a tenant, newest first.

    Used to build the per-tenant bm25s index. `since` lets the cache pull
    only what's appeared since the last rebuild — but the index is rebuilt
    in full on bump, so callers typically pass None.
    """
    pool = await get_db()
    if since is None:
        query = f"""
            SELECT {_COLUMNS} FROM events
            WHERE business_id = $1
            ORDER BY created_at DESC
            LIMIT $2
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, business_id, limit)
    else:
        query = f"""
            SELECT {_COLUMNS} FROM events
            WHERE business_id = $1 AND created_at > $2
            ORDER BY created_at DESC
            LIMIT $3
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, business_id, since, limit)
    return [EventRow(**dict(r)) for r in rows]


async def list_recent_for_customer(
    business_id: UUID,
    customer_id: UUID,
    *,
    limit: int = 20,
) -> list[EventRow]:
    """Recent events for one customer in this tenant, newest first.

    Powers the cluster expansion in `find_customer_clusters` — once bm25
    surfaces a candidate customer, we pull their last N turns to give the
    agent the disambiguation context.
    """
    pool = await get_db()
    query = f"""
        SELECT {_COLUMNS} FROM events
        WHERE business_id = $1 AND customer_id = $2
        ORDER BY created_at DESC
        LIMIT $3
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id, customer_id, limit)
    return [EventRow(**dict(r)) for r in rows]


async def list_recent_for_contact(
    business_id: UUID,
    contact_id: UUID,
    *,
    limit: int = 50,
) -> list[EventRow]:
    """Recent events for one contact in this tenant, newest first."""
    pool = await get_db()
    query = f"""
        SELECT {_COLUMNS} FROM events
        WHERE business_id = $1 AND contact_id = $2
        ORDER BY created_at DESC
        LIMIT $3
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id, contact_id, limit)
    return [EventRow(**dict(r)) for r in rows]


async def find_by_provider_message_id(
    business_id: UUID, provider_message_id: str
) -> EventRow | None:
    """Resolve a quoted-reply id back to the event we sent.

    Used by the inbound webhook to attribute a vendor's quote-reply to the
    exact outbound message (and therefore task_key + customer_id) we sent.
    """
    pool = await get_db()
    query = f"""
        SELECT {_COLUMNS} FROM events
        WHERE business_id = $1 AND provider_message_id = $2
        LIMIT 1
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, business_id, provider_message_id)
    return EventRow(**dict(row)) if row else None
