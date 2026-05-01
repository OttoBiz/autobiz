"""Persistent chat message history for pydantic_ai agents.

Stores pydantic_ai `ModelMessage` sequences per (business_id, customer_id)
conversation. Serialization uses `ModelMessagesTypeAdapter` so the full
fidelity of tool calls, tool returns, and text parts is preserved across
restarts — callers hand back whatever `result.new_messages()` gave them.

Backend: Redis, matching the inbox and cursor stores. A future migration to
Postgres would swap this implementation without changing callers.

Concurrency: `append_history` is a read-modify-write. The orchestrator holds
the per-customer Redis lock for the whole turn, so concurrent writes to the
same conversation are already serialized at the caller level.
"""

from __future__ import annotations

import json
from uuid import UUID

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from pydantic_core import to_jsonable_python

from backend.db.cache_utils import redis_conn

# Bound per-conversation history so a long-running customer doesn't balloon
# memory or token cost on the next turn. 200 covers ~50 turns of tool-heavy
# exchange; revisit once we have production usage data.
MAX_MESSAGES = 200

# Refreshed on every append. 30 days comfortably covers a customer who goes
# quiet for a while and returns mid-flow.
HISTORY_TTL_SECONDS = 30 * 24 * 60 * 60


def _key(business_id: UUID | str, customer_id: UUID | str) -> str:
    return f"chat:{business_id}:{customer_id}"


def _contact_key(business_id: UUID | str, contact_id: UUID | str) -> str:
    return f"contact_chat:{business_id}:{contact_id}"


def _outbound_key(task_key: str) -> str:
    return f"outbound_chat:{task_key}"


async def load_history(
    business_id: UUID | str, customer_id: UUID | str
) -> list[ModelMessage]:
    """Return the stored message history, or [] if none / unreadable."""
    raw = redis_conn._client.get(_key(business_id, customer_id))
    if not raw:
        return []
    try:
        payload = json.loads(raw)
        return ModelMessagesTypeAdapter.validate_python(payload)
    except (ValueError, TypeError):
        # Corrupt / old-schema history — start fresh rather than crash the turn.
        return []


async def append_history(
    business_id: UUID | str,
    customer_id: UUID | str,
    new_messages: list[ModelMessage],
) -> None:
    """Append new messages (typically `result.new_messages()`) to the store.

    No-op on empty `new_messages`. Trims to `MAX_MESSAGES` from the tail and
    refreshes the TTL.
    """
    if not new_messages:
        return
    existing = await load_history(business_id, customer_id)
    combined = existing + list(new_messages)
    if len(combined) > MAX_MESSAGES:
        combined = combined[-MAX_MESSAGES:]
    payload = to_jsonable_python(combined)
    redis_conn._client.set(
        _key(business_id, customer_id),
        json.dumps(payload),
        ex=HISTORY_TTL_SECONDS,
    )


async def clear_history(
    business_id: UUID | str, customer_id: UUID | str
) -> None:
    """Delete the stored history for a conversation. Idempotent."""
    redis_conn._client.delete(_key(business_id, customer_id))


async def load_contact_history(
    business_id: UUID | str, contact_id: UUID | str
) -> list[ModelMessage]:
    """Per-contact vendor/partner conversation history. Same shape as load_history."""
    raw = redis_conn._client.get(_contact_key(business_id, contact_id))
    if not raw:
        return []
    try:
        payload = json.loads(raw)
        return ModelMessagesTypeAdapter.validate_python(payload)
    except (ValueError, TypeError):
        return []


async def append_contact_history(
    business_id: UUID | str,
    contact_id: UUID | str,
    new_messages: list[ModelMessage],
) -> None:
    """Append messages to a contact's conversation. No-op on empty."""
    if not new_messages:
        return
    existing = await load_contact_history(business_id, contact_id)
    combined = existing + list(new_messages)
    if len(combined) > MAX_MESSAGES:
        combined = combined[-MAX_MESSAGES:]
    payload = to_jsonable_python(combined)
    redis_conn._client.set(
        _contact_key(business_id, contact_id),
        json.dumps(payload),
        ex=HISTORY_TTL_SECONDS,
    )


async def clear_contact_history(
    business_id: UUID | str, contact_id: UUID | str
) -> None:
    """Delete the stored history for a contact conversation. Idempotent."""
    redis_conn._client.delete(_contact_key(business_id, contact_id))


async def load_outbound_history(task_key: str) -> list[ModelMessage]:
    """Per-task vendor conversation history. Same shape as load_history."""
    raw = redis_conn._client.get(_outbound_key(task_key))
    if not raw:
        return []
    try:
        payload = json.loads(raw)
        return ModelMessagesTypeAdapter.validate_python(payload)
    except (ValueError, TypeError):
        return []


async def append_outbound_history(
    task_key: str, new_messages: list[ModelMessage]
) -> None:
    """Append messages to a per-task vendor conversation. No-op on empty."""
    if not new_messages:
        return
    existing = await load_outbound_history(task_key)
    combined = existing + list(new_messages)
    if len(combined) > MAX_MESSAGES:
        combined = combined[-MAX_MESSAGES:]
    payload = to_jsonable_python(combined)
    redis_conn._client.set(
        _outbound_key(task_key),
        json.dumps(payload),
        ex=HISTORY_TTL_SECONDS,
    )
