"""Persistent chat message history for pydantic_ai agents.

Stores pydantic_ai `ModelMessage` sequences keyed by an audience tuple.
Today there are three audiences:
- `chat:{business_id}:{customer_id}`         — customer-facing turns
- `contact_chat:{business_id}:{contact_id}`  — vendor/partner-facing turns
- `outbound_chat:{task_key}`                 — legacy per-task history

Serialization uses `ModelMessagesTypeAdapter` so the full fidelity of tool
calls, tool returns, and text parts is preserved across restarts — callers
hand back whatever `result.new_messages()` gave them.

Backend: Redis, matching the inbox and cursor stores. A future migration to
Postgres would swap this implementation without changing callers.

Concurrency: append is a read-modify-write. Each audience has its own
serializing lock at the caller level (orchestrator's per-customer lock,
contact_inbox's per-contact lock).
"""

from __future__ import annotations

import json
from uuid import UUID

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from pydantic_core import to_jsonable_python

from backend.db.cache_utils import redis_conn

# Bound per-conversation history so a long-running thread doesn't balloon
# memory or token cost. 200 covers ~50 turns of tool-heavy exchange.
MAX_MESSAGES = 200

# Refreshed on every append. 30 days comfortably covers a partner who goes
# quiet for a while and returns mid-flow.
HISTORY_TTL_SECONDS = 30 * 24 * 60 * 60


# ---------------------------------------------------------------------------
# Shared internals — all three audiences are the same load/append/clear over
# Redis with a different key prefix. Keep the public surface per-audience so
# call sites stay readable.
# ---------------------------------------------------------------------------


def _customer_key(business_id: UUID | str, customer_id: UUID | str) -> str:
    return f"chat:{business_id}:{customer_id}"


def _contact_key(business_id: UUID | str, contact_id: UUID | str) -> str:
    return f"contact_chat:{business_id}:{contact_id}"


def _outbound_key(task_key: str) -> str:
    return f"outbound_chat:{task_key}"


async def _load(key: str) -> list[ModelMessage]:
    raw = redis_conn._client.get(key)
    if not raw:
        return []
    try:
        payload = json.loads(raw)
        return ModelMessagesTypeAdapter.validate_python(payload)
    except (ValueError, TypeError):
        # Corrupt / old-schema history — start fresh rather than crash the turn.
        return []


async def _append(key: str, new_messages: list[ModelMessage]) -> None:
    if not new_messages:
        return
    existing = await _load(key)
    combined = existing + list(new_messages)
    if len(combined) > MAX_MESSAGES:
        combined = combined[-MAX_MESSAGES:]
    payload = to_jsonable_python(combined)
    redis_conn._client.set(key, json.dumps(payload), ex=HISTORY_TTL_SECONDS)


async def _clear(key: str) -> None:
    redis_conn._client.delete(key)


# ---------------------------------------------------------------------------
# Customer-facing (central agent).
# ---------------------------------------------------------------------------


async def load_history(
    business_id: UUID | str, customer_id: UUID | str
) -> list[ModelMessage]:
    return await _load(_customer_key(business_id, customer_id))


async def append_history(
    business_id: UUID | str,
    customer_id: UUID | str,
    new_messages: list[ModelMessage],
) -> None:
    await _append(_customer_key(business_id, customer_id), new_messages)


async def clear_history(
    business_id: UUID | str, customer_id: UUID | str
) -> None:
    await _clear(_customer_key(business_id, customer_id))


# ---------------------------------------------------------------------------
# Contact-facing (outbound agent).
# ---------------------------------------------------------------------------


async def load_contact_history(
    business_id: UUID | str, contact_id: UUID | str
) -> list[ModelMessage]:
    return await _load(_contact_key(business_id, contact_id))


async def append_contact_history(
    business_id: UUID | str,
    contact_id: UUID | str,
    new_messages: list[ModelMessage],
) -> None:
    await _append(_contact_key(business_id, contact_id), new_messages)


async def clear_contact_history(
    business_id: UUID | str, contact_id: UUID | str
) -> None:
    await _clear(_contact_key(business_id, contact_id))


# ---------------------------------------------------------------------------
# Per-task (legacy — superseded by per-contact; kept until tests migrate).
# ---------------------------------------------------------------------------


async def load_outbound_history(task_key: str) -> list[ModelMessage]:
    return await _load(_outbound_key(task_key))


async def append_outbound_history(
    task_key: str, new_messages: list[ModelMessage]
) -> None:
    await _append(_outbound_key(task_key), new_messages)
