"""Tests for the per-contact debounced inbox.

Mirrors test_inbox.py — fakeredis client wired into cache_utils.redis_conn,
direct calls to enqueue/peek/drain, and a couple of asyncio-driven tests
for the schedule_drain / _drain_after_window plumbing.
"""

from __future__ import annotations

import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "")

import asyncio  # noqa: E402

import fakeredis  # noqa: E402
import pytest  # noqa: E402

from backend.chatbot import contact_inbox  # noqa: E402
from backend.db import cache_utils  # noqa: E402


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache_utils.redis_conn, "_client", client)
    return client


@pytest.fixture(autouse=True)
def clean_scheduled():
    """`SCHEDULED_DRAINS` is module-level; reset between tests."""
    contact_inbox.SCHEDULED_DRAINS.clear()
    yield
    contact_inbox.SCHEDULED_DRAINS.clear()


def test_enqueue_then_peek_returns_messages_in_order():
    contact_inbox.enqueue("biz1", "c1", "first")
    contact_inbox.enqueue("biz1", "c1", "second")
    contact_inbox.enqueue("biz1", "c1", "third")

    assert contact_inbox.peek("biz1", "c1") == ["first", "second", "third"]


def test_drain_clears_inbox():
    contact_inbox.enqueue("biz1", "c1", "hello")
    contact_inbox.enqueue("biz1", "c1", "world")
    assert contact_inbox.peek("biz1", "c1") == ["hello", "world"]

    contact_inbox.drain("biz1", "c1")
    assert contact_inbox.peek("biz1", "c1") == []


def test_acquire_lock_prevents_double_acquire():
    assert contact_inbox.acquire_lock("biz1", "c1", "owner-A") is True
    # Different owner can't grab it.
    assert contact_inbox.acquire_lock("biz1", "c1", "owner-B") is False
    # Releasing with the right owner allows the next acquire.
    assert contact_inbox.release_lock("biz1", "c1", "owner-A") is True
    assert contact_inbox.acquire_lock("biz1", "c1", "owner-B") is True


def test_release_lock_with_wrong_owner_is_noop():
    contact_inbox.acquire_lock("biz1", "c1", "owner-A")
    assert contact_inbox.release_lock("biz1", "c1", "owner-B") is False
    # Lock still held by A.
    assert contact_inbox.acquire_lock("biz1", "c1", "owner-C") is False


def test_enqueue_sets_ttl(fake_redis):
    contact_inbox.enqueue("biz1", "c1", "msg")
    ttl = fake_redis.ttl("contact_inbox:biz1:c1")
    assert 0 < ttl <= contact_inbox.INBOX_TTL_SECONDS


@pytest.mark.asyncio
async def test_schedule_drain_dedupes_within_window(monkeypatch):
    monkeypatch.setattr(contact_inbox, "DRAIN_WINDOW_SECONDS", 0.1)

    calls: list[tuple[str, str, list[str]]] = []

    async def runner(biz: str, cid: str, messages: list[str]) -> None:
        calls.append((biz, cid, messages))

    contact_inbox.enqueue("biz1", "c1", "first")

    await contact_inbox.schedule_drain("biz1", "c1", runner)
    # Second call within the window must not spawn a second drain task.
    await contact_inbox.schedule_drain("biz1", "c1", runner)

    contact_inbox.enqueue("biz1", "c1", "second")

    # Wait for the window to fire.
    await asyncio.sleep(0.25)

    assert len(calls) == 1
    biz, cid, messages = calls[0]
    assert biz == "biz1"
    assert cid == "c1"
    assert messages == ["first", "second"]
    # Inbox cleared after successful drain.
    assert contact_inbox.peek("biz1", "c1") == []


@pytest.mark.asyncio
async def test_drain_after_window_calls_runner_with_peeked_messages(monkeypatch):
    monkeypatch.setattr(contact_inbox, "DRAIN_WINDOW_SECONDS", 0.1)

    captured: dict = {}

    async def runner(biz: str, cid: str, messages: list[str]) -> None:
        captured["args"] = (biz, cid, messages)

    contact_inbox.enqueue("biz1", "c1", "yes")
    contact_inbox.enqueue("biz1", "c1", "5 in stock")

    await contact_inbox.schedule_drain("biz1", "c1", runner)
    await asyncio.sleep(0.25)

    assert captured["args"] == ("biz1", "c1", ["yes", "5 in stock"])
    assert contact_inbox.peek("biz1", "c1") == []


@pytest.mark.asyncio
async def test_runner_exception_leaves_inbox_intact(monkeypatch):
    monkeypatch.setattr(contact_inbox, "DRAIN_WINDOW_SECONDS", 0.1)

    async def boom(biz: str, cid: str, messages: list[str]) -> None:
        raise RuntimeError("agent fell over")

    contact_inbox.enqueue("biz1", "c1", "stuck")

    await contact_inbox.schedule_drain("biz1", "c1", boom)
    await asyncio.sleep(0.25)

    # On runner failure the messages remain queued so a subsequent inbound
    # can schedule another drain that gets a fresh chance.
    assert contact_inbox.peek("biz1", "c1") == ["stuck"]


@pytest.mark.asyncio
async def test_schedule_drain_after_first_completes_can_schedule_again(monkeypatch):
    """Once a drain completes, a fresh schedule_drain must work — the
    SCHEDULED_DRAINS marker is cleared the moment the timer wakes up."""
    monkeypatch.setattr(contact_inbox, "DRAIN_WINDOW_SECONDS", 0.05)

    runs: list[list[str]] = []

    async def runner(biz: str, cid: str, messages: list[str]) -> None:
        runs.append(messages)

    contact_inbox.enqueue("biz1", "c1", "first")
    await contact_inbox.schedule_drain("biz1", "c1", runner)
    await asyncio.sleep(0.15)

    # Second batch — should fire its own drain.
    contact_inbox.enqueue("biz1", "c1", "second")
    await contact_inbox.schedule_drain("biz1", "c1", runner)
    await asyncio.sleep(0.15)

    assert runs == [["first"], ["second"]]
