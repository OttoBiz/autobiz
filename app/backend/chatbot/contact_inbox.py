"""Per-contact inbox with a debounced drain window.

Vendors send inbound messages in bursts ("yes", "5 units", "₦15k each") —
each as a separate WhatsApp message arriving microseconds apart. Running
the outbound agent once per inbound is wasteful (3× model calls, 3× sent
replies) and produces awkward back-and-forth.

The flow:

1. Webhook enqueues each inbound onto a per-contact list, then schedules
   a single drain task that sleeps for `DRAIN_WINDOW_SECONDS` before
   running.
2. Subsequent messages within that window just append to the list — they
   don't schedule a second drain (`SCHEDULED_DRAINS` dedupes in-process).
3. When the timer fires, the drain task acquires the per-contact mutex,
   peeks all pending messages, joins them with newlines, runs the agent
   once, sends one reply, drains the list, releases the mutex.

Single-instance assumption: in-process `SCHEDULED_DRAINS` deduplication
means two backend replicas could each schedule a drain for the same
contact-window. The Redis mutex would still serialize them, so the worst
case is one no-op drain (peek returns empty because the first drain
already cleared). Acceptable for current single-container deployment.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

from backend.db.cache_utils import redis_conn

logger = logging.getLogger(__name__)

DRAIN_WINDOW_SECONDS = 20
INBOX_TTL_SECONDS = 24 * 60 * 60
LOCK_TTL_SECONDS = 60


def _inbox_key(business_id: str, contact_id: str) -> str:
    return f"contact_inbox:{business_id}:{contact_id}"


def _lock_key(business_id: str, contact_id: str) -> str:
    return f"lock:contact_inbox:{business_id}:{contact_id}"


# In-process set of contact IDs that already have a pending drain task.
# Cleared by the drain task after it acquires the lock — at that point
# any newly-enqueued message must schedule a fresh drain to be picked up.
SCHEDULED_DRAINS: set[tuple[str, str]] = set()


def enqueue(business_id: str, contact_id: str, text: str) -> None:
    key = _inbox_key(business_id, contact_id)
    client = redis_conn._client
    pipe = client.pipeline(transaction=True)
    pipe.rpush(key, json.dumps({"text": text}))
    pipe.expire(key, INBOX_TTL_SECONDS)
    pipe.execute()


def peek(business_id: str, contact_id: str) -> list[str]:
    key = _inbox_key(business_id, contact_id)
    items = redis_conn._client.lrange(key, 0, -1)
    out: list[str] = []
    for raw in items:
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            continue
        text = payload.get("text") or ""
        if text:
            out.append(text)
    return out


def drain(business_id: str, contact_id: str) -> None:
    key = _inbox_key(business_id, contact_id)
    redis_conn._client.delete(key)


def acquire_lock(business_id: str, contact_id: str, owner: str) -> bool:
    key = _lock_key(business_id, contact_id)
    return bool(redis_conn._client.set(key, owner, nx=True, ex=LOCK_TTL_SECONDS))


def release_lock(business_id: str, contact_id: str, owner: str) -> bool:
    key = _lock_key(business_id, contact_id)
    client = redis_conn._client
    with client.pipeline(transaction=True) as pipe:
        while True:
            try:
                pipe.watch(key)
                current = pipe.get(key)
                if isinstance(current, bytes):
                    current = current.decode()
                if current != owner:
                    pipe.unwatch()
                    return False
                pipe.multi()
                pipe.delete(key)
                pipe.execute()
                return True
            except Exception:
                continue


async def schedule_drain(
    business_id: str,
    contact_id: str,
    runner: Callable[[str, str, list[str]], Awaitable[None]],
) -> None:
    """Schedule a debounced drain. No-op if one is already pending.

    `runner` is the per-call callback invoked under the mutex with the
    coalesced message list — typically the outbound agent's contact-reply
    runner. Decoupled here so this module stays infrastructural.
    """
    key = (business_id, contact_id)
    if key in SCHEDULED_DRAINS:
        return
    SCHEDULED_DRAINS.add(key)
    asyncio.create_task(_drain_after_window(business_id, contact_id, runner))


async def _drain_after_window(
    business_id: str,
    contact_id: str,
    runner: Callable[[str, str, list[str]], Awaitable[None]],
) -> None:
    try:
        await asyncio.sleep(DRAIN_WINDOW_SECONDS)
    finally:
        # Clear the scheduled flag the moment we wake — any message that
        # arrives from this point on must schedule a fresh drain.
        SCHEDULED_DRAINS.discard((business_id, contact_id))

    # uuid for the lock owner — this drain task instance.
    from uuid import uuid4

    owner = uuid4().hex
    if not acquire_lock(business_id, contact_id, owner):
        # Another drain is already running for this contact (shouldn't
        # happen in single-instance, but stays correct under contention).
        logger.info(
            "contact_inbox drain skipped — lock held biz=%s contact=%s",
            business_id,
            contact_id,
        )
        return
    try:
        messages = peek(business_id, contact_id)
        if not messages:
            return
        try:
            await runner(business_id, contact_id, messages)
        except Exception:
            # On runner failure we leave messages queued; a subsequent
            # inbound will schedule another drain that gets a fresh chance.
            logger.exception(
                "contact_inbox runner failed biz=%s contact=%s", business_id, contact_id
            )
            return
        drain(business_id, contact_id)
    finally:
        release_lock(business_id, contact_id, owner)
