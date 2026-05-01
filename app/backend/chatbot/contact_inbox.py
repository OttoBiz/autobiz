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

Queue + lock primitives delegate to `_redis_queue` (shared with the
per-customer inbox in chatbot/inbox.py).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable
from uuid import uuid4

from backend.chatbot import _redis_queue

logger = logging.getLogger(__name__)

DRAIN_WINDOW_SECONDS = 20
INBOX_TTL_SECONDS = 24 * 60 * 60
LOCK_TTL_SECONDS = 60


def _inbox_key(business_id: str, contact_id: str) -> str:
    return f"contact_inbox:{business_id}:{contact_id}"


def _lock_key(business_id: str, contact_id: str) -> str:
    return f"lock:contact_inbox:{business_id}:{contact_id}"


# In-process set of contact IDs that already have a pending drain task.
# Cleared by the drain task on wake — at that point any newly-enqueued
# message must schedule a fresh drain to be picked up.
SCHEDULED_DRAINS: set[tuple[str, str]] = set()


def enqueue(business_id: str, contact_id: str, text: str) -> None:
    _redis_queue.push(
        _inbox_key(business_id, contact_id),
        {"text": text},
        ttl_seconds=INBOX_TTL_SECONDS,
    )


def peek(business_id: str, contact_id: str) -> list[str]:
    items = _redis_queue.peek(_inbox_key(business_id, contact_id))
    return [item.get("text", "") for item in items if item.get("text")]


def drain(business_id: str, contact_id: str) -> None:
    _redis_queue.clear(_inbox_key(business_id, contact_id))


def acquire_lock(business_id: str, contact_id: str, owner: str) -> bool:
    return _redis_queue.acquire_lock(
        _lock_key(business_id, contact_id), owner, ttl_seconds=LOCK_TTL_SECONDS
    )


def release_lock(business_id: str, contact_id: str, owner: str) -> bool:
    return _redis_queue.release_lock(_lock_key(business_id, contact_id), owner)


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
