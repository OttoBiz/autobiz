import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "")

from datetime import datetime, timezone  # noqa: E402

import fakeredis  # noqa: E402
import pytest  # noqa: E402

from backend.chatbot import inbox  # noqa: E402
from backend.db import cache_utils  # noqa: E402


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache_utils.redis_conn, "_client", client)
    return client


def test_enqueue_drain_round_trip():
    inbox.enqueue("biz1", "cust1", {"type": "user_message", "payload": {"text": "hi"}})
    inbox.enqueue("biz1", "cust1", {"type": "system_event", "payload": {"kind": "ping"}})

    items = inbox.drain("biz1", "cust1")

    assert items == [
        {"type": "user_message", "payload": {"text": "hi"}},
        {"type": "system_event", "payload": {"kind": "ping"}},
    ]
    assert inbox.drain("biz1", "cust1") == []


def test_peek_is_non_destructive():
    inbox.enqueue("biz1", "cust1", {"type": "user_message", "payload": {"text": "hi"}})

    assert inbox.peek("biz1", "cust1") == [{"type": "user_message", "payload": {"text": "hi"}}]
    assert inbox.peek("biz1", "cust1") == [{"type": "user_message", "payload": {"text": "hi"}}]


def test_enqueue_sets_expire(fake_redis):
    inbox.enqueue("biz1", "cust1", {"type": "user_message", "payload": {}})

    ttl = fake_redis.ttl("inbox:biz1:cust1")
    assert 0 < ttl <= inbox.INBOX_TTL_SECONDS


def test_lock_acquire_blocks_second_owner():
    assert inbox.acquire_lock("biz1", "cust1", owner="A") is True
    assert inbox.acquire_lock("biz1", "cust1", owner="B") is False


def test_lock_release_owner_match():
    inbox.acquire_lock("biz1", "cust1", owner="A")
    assert inbox.release_lock("biz1", "cust1", owner="A") is True
    assert inbox.acquire_lock("biz1", "cust1", owner="B") is True


def test_lock_release_owner_mismatch_is_noop():
    inbox.acquire_lock("biz1", "cust1", owner="A")
    assert inbox.release_lock("biz1", "cust1", owner="B") is False
    assert inbox.acquire_lock("biz1", "cust1", owner="C") is False


def test_lock_release_missing_lock_is_noop():
    assert inbox.release_lock("biz1", "cust1", owner="A") is False


def test_cursor_get_set_round_trip():
    assert inbox.get_cursor("biz1", "cust1") is None

    ts = datetime(2026, 4, 22, 12, 30, 45, tzinfo=timezone.utc)
    inbox.set_cursor("biz1", "cust1", ts)

    assert inbox.get_cursor("biz1", "cust1") == ts


def test_cursor_naive_datetime_treated_as_utc():
    naive = datetime(2026, 4, 22, 12, 30, 45)
    inbox.set_cursor("biz1", "cust1", naive)

    assert inbox.get_cursor("biz1", "cust1") == naive.replace(tzinfo=timezone.utc)
