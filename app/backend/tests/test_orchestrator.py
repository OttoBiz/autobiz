"""Tests for the channel-agnostic orchestrator.

Mocks every I/O boundary: inbox (Redis), ledger (Postgres), channel registry,
channel.send, channel_identities.upsert_identity, and central_agent.run. Covers
the happy path, lock contention, drain-after-success atomicity, prompt shape,
and the WhatsApp webhook wiring.
"""

from __future__ import annotations

import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "")

from datetime import datetime, timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.chatbot import orchestrator  # noqa: E402
from backend.chatbot.channels.base import (  # noqa: E402
    ChannelIdentity,
    InboundMessage,
)


_BIZ_ID = str(uuid4())
_CUST_ID = str(uuid4())


def _identity() -> ChannelIdentity:
    return ChannelIdentity(
        business_id=_BIZ_ID,
        customer_id=_CUST_ID,
        channel="whatsapp",
        channel_user_id="cust1",
        last_inbound_at=None,
    )


def _inbound(text: str = "hello") -> InboundMessage:
    return InboundMessage(
        identity=_identity(),
        text=text,
        media=[],
        raw={"sample": True},
        received_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def patch_inbox(monkeypatch):
    acquire = MagicMock(return_value=True)
    release = MagicMock(return_value=True)
    enqueue = MagicMock()
    drain = MagicMock(return_value=[])
    peek = MagicMock(return_value=[])
    monkeypatch.setattr(orchestrator.inbox, "acquire_lock", acquire)
    monkeypatch.setattr(orchestrator.inbox, "release_lock", release)
    monkeypatch.setattr(orchestrator.inbox, "enqueue", enqueue)
    monkeypatch.setattr(orchestrator.inbox, "drain", drain)
    monkeypatch.setattr(orchestrator.inbox, "peek", peek)
    return SimpleNamespace(
        acquire=acquire,
        release=release,
        enqueue=enqueue,
        drain=drain,
        peek=peek,
    )


@pytest.fixture
def patch_identity(monkeypatch):
    upsert = AsyncMock()
    monkeypatch.setattr(
        orchestrator.channel_identities, "upsert_identity", upsert
    )
    return upsert


@pytest.fixture
def patch_central(monkeypatch):
    new_messages = MagicMock(return_value=["msg-a", "msg-b"])
    run = AsyncMock(
        return_value=SimpleNamespace(
            output="agent reply", new_messages=new_messages
        )
    )
    monkeypatch.setattr(orchestrator.central_agent, "run", run)
    return run


@pytest.fixture
def patch_chat_storage(monkeypatch):
    load = AsyncMock(return_value=[])
    append = AsyncMock()
    monkeypatch.setattr(orchestrator.chat_storage, "load_history", load)
    monkeypatch.setattr(orchestrator.chat_storage, "append_history", append)
    return SimpleNamespace(load=load, append=append)


@pytest.fixture
def patch_registry(monkeypatch):
    channel = SimpleNamespace(
        send=AsyncMock(),
        send_flow=AsyncMock(),
        name="whatsapp",
    )
    get = MagicMock(return_value=channel)
    monkeypatch.setattr(orchestrator.registry, "get", get)
    return SimpleNamespace(get=get, channel=channel)


@pytest.mark.asyncio
async def test_happy_path_runs_central_sends_and_drains_after(
    patch_inbox, patch_identity, patch_central, patch_registry, patch_chat_storage
):
    msg = _inbound("hi there")
    # Mirror real Redis: peek returns whatever was just enqueued.
    patch_inbox.peek.return_value = [
        {"type": "user_message", "payload": {"text": "hi there"}}
    ]
    patch_chat_storage.load.return_value = ["prior-msg"]

    await orchestrator.handle_inbound(msg)

    patch_inbox.acquire.assert_called_once()
    patch_identity.assert_awaited_once()
    patch_inbox.enqueue.assert_called_once()
    patch_central.assert_awaited_once()
    prompt_arg = patch_central.await_args.args[0]
    assert "hi there" in prompt_arg
    # message_history loaded from chat_storage and threaded through.
    assert patch_central.await_args.kwargs["message_history"] == ["prior-msg"]
    patch_registry.channel.send.assert_awaited_once_with(msg.identity, "agent reply")
    patch_inbox.drain.assert_called_once_with(_BIZ_ID, _CUST_ID)
    patch_chat_storage.append.assert_awaited_once_with(
        _BIZ_ID, _CUST_ID, ["msg-a", "msg-b"]
    )
    patch_inbox.release.assert_called_once()


@pytest.mark.asyncio
async def test_lock_contention_enqueues_without_running_central(
    patch_inbox, patch_identity, patch_central, patch_registry, patch_chat_storage
):
    patch_inbox.acquire.return_value = False

    await orchestrator.handle_inbound(_inbound())

    patch_inbox.enqueue.assert_called_once()
    patch_central.assert_not_awaited()
    patch_registry.channel.send.assert_not_awaited()
    patch_inbox.drain.assert_not_called()
    patch_identity.assert_not_awaited()
    patch_chat_storage.load.assert_not_awaited()
    patch_chat_storage.append.assert_not_awaited()
    # Lock was never held by us, so we must not release it.
    patch_inbox.release.assert_not_called()


@pytest.mark.asyncio
async def test_drain_skipped_when_send_fails(
    patch_inbox, patch_identity, patch_central, patch_registry, patch_chat_storage
):
    # Seed peek so _drain_and_reply actually runs central + dispatch; the test
    # is checking that a send failure aborts drain, not the empty-queue path.
    patch_inbox.peek.return_value = [
        {"type": "user_message", "payload": {"text": "hello"}}
    ]
    patch_registry.channel.send.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await orchestrator.handle_inbound(_inbound())

    patch_central.assert_awaited_once()
    patch_inbox.drain.assert_not_called()
    # History must NOT be persisted on failure — the failed turn would otherwise
    # be replayed twice (once now, once when the inbox items get re-processed).
    patch_chat_storage.append.assert_not_awaited()
    # Lock must always release.
    patch_inbox.release.assert_called_once()


def test_build_prompt_contains_user_and_system_items():
    items = [
        {"type": "user_message", "payload": {"text": "where is my order?"}},
        {"type": "system_event", "payload": {"summary": "vendor pinged"}},
    ]

    prompt = orchestrator._build_prompt(items)

    assert "Customer messages this turn:" in prompt
    assert "- where is my order?" in prompt
    assert "- (system) vendor pinged" in prompt
    # Outbound state is no longer pushed in — central pulls via tool.
    assert "Pending outbound tasks" not in prompt
    assert "Recently resolved" not in prompt


def test_whatsapp_webhook_invokes_orchestrator(monkeypatch):
    from backend.api.routers.webhooks import whatsapp as whatsapp_webhook
    from backend.chatbot.channels.whatsapp_resolver import InboundSender
    from uuid import UUID as _UUID

    captured: dict = {}

    async def fake_handle_inbound(msg: InboundMessage) -> None:
        captured["msg"] = msg

    fake_msg = _inbound("from webhook")
    fake_channel = SimpleNamespace(parse_inbound=MagicMock(return_value=fake_msg))

    biz_uuid = _UUID(_BIZ_ID)
    cust_uuid = _UUID(_CUST_ID)

    async def fake_resolve_sender(phone_number_id, wa_id):
        return InboundSender(kind="customer", business_id=biz_uuid)

    async def fake_resolve_customer(wa_id):
        return cust_uuid

    monkeypatch.setattr(whatsapp_webhook.orchestrator, "handle_inbound", fake_handle_inbound)
    monkeypatch.setattr(whatsapp_webhook.registry, "get", lambda name: fake_channel)
    monkeypatch.setattr(
        whatsapp_webhook, "resolve_inbound_sender", fake_resolve_sender
    )
    monkeypatch.setattr(
        whatsapp_webhook,
        "resolve_or_create_customer_by_phone",
        fake_resolve_customer,
    )
    # Bypass HMAC check; APP_SECRET unset in tests so verify_signature returns True.

    app = FastAPI()
    app.include_router(whatsapp_webhook.router)

    payload = {"entry": [{"changes": [{"value": {"sample": True}}]}]}
    with TestClient(app) as client:
        response = client.post("/webhooks/whatsapp", json=payload)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    fake_channel.parse_inbound.assert_called_once_with(payload)
    # The webhook rewrites identity with the resolved UUIDs before calling
    # handle_inbound, so we can't compare msg-by-identity; just confirm it
    # arrived and the body text was preserved.
    assert "msg" in captured
    assert captured["msg"].text == "from webhook"
    assert captured["msg"].identity.business_id == _BIZ_ID
    assert captured["msg"].identity.customer_id == _CUST_ID
