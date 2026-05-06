"""Unified per-party inbox: queue + debounced drain + idempotency.

One module for both customer-side and vendor-side conversations. Each party
(customer or vendor) has:
- A Redis list of items (`{type, payload, enqueued_at, dedup_key}`)
- A per-party Redis mutex for serializing drains
- A 10s debounce window: bursts coalesce into one drain
- A dedup key on each ingest: Meta webhook retries are absorbed silently

Lifecycle:
1. `ingest(party, item, *, dedup_id, runner)` — webhooks and the after_tool_execute
   hook call this. Returns False if the dedup_id was seen in the last 24h.
2. After ingest, a single drain task is scheduled for the party. Subsequent
   ingests inside the 10s window do not schedule additional drains
   (deduped via in-process SCHEDULED_DRAINS set).
3. When the timer fires, the drain task acquires the per-party lock, peeks all
   items, calls `runner(party, items)`, and on success drains exactly those
   items (LREM by token). Items that arrived during the run survive.
4. If a drain was requested while another was running (PENDING_REDRAIN), the
   active drain re-loops instead of releasing.
5. After release, any items still queued schedule a fresh drain.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Literal
from uuid import uuid4

from backend.chatbot import _redis_queue

logger = logging.getLogger(__name__)

DRAIN_WINDOW_SECONDS = 2
INBOX_TTL_SECONDS = 24 * 60 * 60
LOCK_TTL_SECONDS = 60
DEDUP_TTL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class PartyKey:
    """Identifies one conversation participant. business_id + party_id are strings.

    `kind` exists so customer and vendor namespaces don't collide if the same UUID
    is reused across roles (extremely unlikely but cheap to guard against).
    """

    kind: Literal["customer", "vendor"]
    business_id: str
    party_id: str

    @classmethod
    def customer(cls, business_id: str, customer_id: str) -> "PartyKey":
        return cls("customer", str(business_id), str(customer_id))

    @classmethod
    def vendor(cls, business_id: str, contact_id: str) -> "PartyKey":
        return cls("vendor", str(business_id), str(contact_id))


# Runner: called by the drain task with all peeked items.
# Raises on transient failure → items remain queued, drain reschedules later.
DrainRunner = Callable[[PartyKey, list[dict]], Awaitable[None]]


def _inbox_key(p: PartyKey) -> str:
    return f"inbox:{p.kind}:{p.business_id}:{p.party_id}"


def _lock_key(p: PartyKey) -> str:
    return f"lock:inbox:{p.kind}:{p.business_id}:{p.party_id}"


def _dedup_key(dedup_id: str) -> str:
    return f"inbox:dedup:{dedup_id}"


# In-process. Acceptable: single-instance deployment. Two replicas would each
# schedule a drain; the Redis lock still serializes, the second drain peeks
# empty and exits. Same semantics as the old contact_inbox module.
_SCHEDULED_DRAINS: set[PartyKey] = set()
_PENDING_REDRAIN: set[PartyKey] = set()


def ingest(
    party: PartyKey,
    item: dict,
    *,
    dedup_id: str | None,
    runner: DrainRunner,
) -> bool:
    """Enqueue `item` and ensure a drain is scheduled. Returns False on duplicate.

    `item` shape (enforced by convention, not type):
        {"type": "user_message" | "system_event",
         "payload": {...},
         "enqueued_at": <iso str>,
         "dedup_key": <str | None>}

    `dedup_id` is the unique id for the source event:
        - WhatsApp inbound: msg.raw["messages"][0]["id"] (the wamid.* string)
        - HTTP/console inbound: a stable hash of (party, text, timestamp) — or None
          if the channel can't produce one (then dedup is a no-op).
        - resolve hook: f"resolve:{task_key}"
        - surface_to_customer: f"surface:{task_key}:{uuid4().hex}"

    `runner` is the drain pipeline for this party. Stash it on the scheduled
    drain task so it always uses the right pipeline.
    """
    if dedup_id is not None:
        if not _redis_queue.set_if_absent(_dedup_key(dedup_id), "1", DEDUP_TTL_SECONDS):
            logger.info("ingest deduped party=%s dedup_id=%s", party, dedup_id)
            return False
    _redis_queue.push(_inbox_key(party), item, ttl_seconds=INBOX_TTL_SECONDS)
    _schedule_drain(party, runner)
    return True


def peek(party: PartyKey) -> list[dict]:
    """Read all queued items without removing them."""
    return [parsed for _, parsed in _redis_queue.peek_with_tokens(_inbox_key(party))]


def _peek_with_tokens(party: PartyKey) -> list[tuple[str, dict]]:
    return _redis_queue.peek_with_tokens(_inbox_key(party))


def _schedule_drain(party: PartyKey, runner: DrainRunner) -> None:
    if party in _SCHEDULED_DRAINS:
        # A drain is already pending; if one is currently running, mark it
        # for redrain so it loops instead of releasing.
        _PENDING_REDRAIN.add(party)
        return
    _SCHEDULED_DRAINS.add(party)
    asyncio.create_task(_drain_after_window(party, runner))


async def _drain_after_window(party: PartyKey, runner: DrainRunner) -> None:
    try:
        await asyncio.sleep(DRAIN_WINDOW_SECONDS)
    finally:
        _SCHEDULED_DRAINS.discard(party)

    owner = uuid4().hex
    if not _redis_queue.acquire_lock(
        _lock_key(party), owner, ttl_seconds=LOCK_TTL_SECONDS
    ):
        # Another drain is in flight. Mark redrain so it loops on completion.
        _PENDING_REDRAIN.add(party)
        return

    try:
        while True:
            tokens_and_items = _peek_with_tokens(party)
            if not tokens_and_items:
                break
            tokens = [t for t, _ in tokens_and_items]
            items = [i for _, i in tokens_and_items]
            try:
                await runner(party, items)
            except Exception:
                logger.exception("drain runner failed party=%s", party)
                # Leave items queued for the next drain. Do NOT drain on failure.
                return
            _redis_queue.drain_specific(_inbox_key(party), tokens)
            # Did anyone request a redrain while we ran?
            if party not in _PENDING_REDRAIN:
                break
            _PENDING_REDRAIN.discard(party)
    finally:
        _redis_queue.release_lock(_lock_key(party), owner)
        # Trailing safety: if a webhook ingest happened after we cleared
        # SCHEDULED_DRAINS but bailed because the lock was held, ensure
        # those items get a fresh drain.
        if peek(party):
            _schedule_drain(party, runner)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_user_message_item(
    *,
    text: str,
    raw: dict | None = None,
    dedup_id: str | None = None,
    media: list[dict] | None = None,
) -> dict:
    """Build an inbox user-message item.

    `media` is a list of `{kind, url, mime_type}` dicts populated by the
    webhook after it has resolved the channel-native media id to a URL the
    model can fetch. Stored alongside the text so the conversation drainer
    can hand both to the agent.
    """
    return {
        "type": "user_message",
        "payload": {"text": text, "raw": raw or {}, "media": media or []},
        "enqueued_at": now_iso(),
        "dedup_key": dedup_id,
    }


def make_system_event_item(
    *, summary: str, source: str, dedup_id: str | None = None, **extras
) -> dict:
    payload = {"summary": summary, "source": source, **extras}
    return {
        "type": "system_event",
        "payload": payload,
        "enqueued_at": now_iso(),
        "dedup_key": dedup_id,
    }
