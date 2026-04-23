"""Tests for the pydantic_ai message-history store.

Backed by a fake in-memory dict that mimics the Redis ops we use (get / set /
delete) — keeps tests hermetic without a live Redis. Round-trips real
pydantic_ai message objects so we catch any serializer/validator drift.
"""

from __future__ import annotations

import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "")

from datetime import datetime, timezone  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402
from pydantic_ai.messages import (  # noqa: E402
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from backend.db import chat_storage  # noqa: E402


class _FakeRedis:
    """Just enough Redis surface for chat_storage."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None):
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex

    def delete(self, key: str):
        self.store.pop(key, None)
        self.ttls.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(chat_storage.redis_conn, "_client", fake)
    return fake


def _msgs() -> list:
    """One request/response pair — minimal but exercises both message types."""
    return [
        ModelRequest(
            parts=[UserPromptPart(content="hi", timestamp=datetime.now(timezone.utc))]
        ),
        ModelResponse(parts=[TextPart(content="hello")]),
    ]


@pytest.mark.asyncio
async def test_load_returns_empty_when_nothing_stored(fake_redis):
    history = await chat_storage.load_history(uuid4(), uuid4())
    assert history == []


@pytest.mark.asyncio
async def test_append_then_load_round_trips_messages(fake_redis):
    biz, cust = uuid4(), uuid4()
    msgs = _msgs()

    await chat_storage.append_history(biz, cust, msgs)
    loaded = await chat_storage.load_history(biz, cust)

    assert len(loaded) == 2
    assert isinstance(loaded[0], ModelRequest)
    assert isinstance(loaded[1], ModelResponse)
    assert loaded[1].parts[0].content == "hello"
    # TTL set on write.
    assert fake_redis.ttls[chat_storage._key(biz, cust)] == chat_storage.HISTORY_TTL_SECONDS


@pytest.mark.asyncio
async def test_append_concatenates_across_calls(fake_redis):
    biz, cust = uuid4(), uuid4()

    await chat_storage.append_history(biz, cust, _msgs())
    await chat_storage.append_history(biz, cust, _msgs())

    loaded = await chat_storage.load_history(biz, cust)
    assert len(loaded) == 4


@pytest.mark.asyncio
async def test_append_trims_to_max_messages(fake_redis, monkeypatch):
    monkeypatch.setattr(chat_storage, "MAX_MESSAGES", 3)
    biz, cust = uuid4(), uuid4()

    # Five total — should be trimmed to the newest 3.
    pairs = _msgs() + _msgs() + [ModelResponse(parts=[TextPart(content="latest")])]
    await chat_storage.append_history(biz, cust, pairs)

    loaded = await chat_storage.load_history(biz, cust)
    assert len(loaded) == 3
    assert loaded[-1].parts[0].content == "latest"


@pytest.mark.asyncio
async def test_append_empty_list_is_noop(fake_redis):
    biz, cust = uuid4(), uuid4()
    await chat_storage.append_history(biz, cust, [])
    assert fake_redis.store == {}


@pytest.mark.asyncio
async def test_clear_removes_history(fake_redis):
    biz, cust = uuid4(), uuid4()
    await chat_storage.append_history(biz, cust, _msgs())
    await chat_storage.clear_history(biz, cust)
    assert await chat_storage.load_history(biz, cust) == []


@pytest.mark.asyncio
async def test_load_recovers_from_corrupt_payload(fake_redis):
    biz, cust = uuid4(), uuid4()
    fake_redis.store[chat_storage._key(biz, cust)] = "{not valid json"

    # Should not raise — corrupt history degrades to empty.
    assert await chat_storage.load_history(biz, cust) == []


@pytest.mark.asyncio
async def test_outbound_history_round_trips_per_task_key(fake_redis):
    task_key = "tk-abc"

    await chat_storage.append_outbound_history(task_key, _msgs())
    loaded = await chat_storage.load_outbound_history(task_key)

    assert len(loaded) == 2
    assert loaded[1].parts[0].content == "hello"
    # Stored under the per-task key, not the per-customer key.
    assert chat_storage._outbound_key(task_key) in fake_redis.store


@pytest.mark.asyncio
async def test_outbound_history_isolates_tasks(fake_redis):
    await chat_storage.append_outbound_history("tk-1", _msgs())
    await chat_storage.append_outbound_history("tk-2", _msgs() + _msgs())

    assert len(await chat_storage.load_outbound_history("tk-1")) == 2
    assert len(await chat_storage.load_outbound_history("tk-2")) == 4
