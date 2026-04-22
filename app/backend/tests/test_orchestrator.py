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

from datetime import datetime, timedelta, timezone  # noqa: E402
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
from backend.chatbot.messaging.reply import Reply  # noqa: E402
from backend.db.outbound_ledger import OutboundTaskRow  # noqa: E402


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


def _task(
    *,
    state: str = "succeeded",
    customer_context: str | None = None,
    party: str = "vendor-x",
    dispatch_prompt: str = "ask vendor",
    resolved_at: datetime | None = None,
) -> OutboundTaskRow:
    now = datetime.now(timezone.utc)
    return OutboundTaskRow(
        task_key=f"tk-{uuid4().hex[:6]}",
        business_id=uuid4(),
        customer_id=uuid4(),
        party=party,
        initiated_by="customer",
        dispatch_prompt=dispatch_prompt,
        state=state,  # type: ignore[arg-type]
        customer_context=customer_context,
        system_context=None,
        dispatched_at=now,
        resolved_at=resolved_at if resolved_at is not None else now,
        timeout_at=now + timedelta(minutes=5),
    )


@pytest.fixture
def patch_inbox(monkeypatch):
    acquire = MagicMock(return_value=True)
    release = MagicMock(return_value=True)
    enqueue = MagicMock()
    drain = MagicMock(return_value=[])
    peek = MagicMock(return_value=[])
    get_cursor = MagicMock(return_value=None)
    set_cursor = MagicMock()
    monkeypatch.setattr(orchestrator.inbox, "acquire_lock", acquire)
    monkeypatch.setattr(orchestrator.inbox, "release_lock", release)
    monkeypatch.setattr(orchestrator.inbox, "enqueue", enqueue)
    monkeypatch.setattr(orchestrator.inbox, "drain", drain)
    monkeypatch.setattr(orchestrator.inbox, "peek", peek)
    monkeypatch.setattr(orchestrator.inbox, "get_cursor", get_cursor)
    monkeypatch.setattr(orchestrator.inbox, "set_cursor", set_cursor)
    return SimpleNamespace(
        acquire=acquire,
        release=release,
        enqueue=enqueue,
        drain=drain,
        peek=peek,
        get_cursor=get_cursor,
        set_cursor=set_cursor,
    )


@pytest.fixture
def patch_ledger(monkeypatch):
    pending = AsyncMock(return_value=[])
    resolved = AsyncMock(return_value=[])
    monkeypatch.setattr(
        orchestrator.outbound_ledger, "get_pending_for_customer", pending
    )
    monkeypatch.setattr(
        orchestrator.outbound_ledger, "get_resolved_since", resolved
    )
    return SimpleNamespace(pending=pending, resolved=resolved)


@pytest.fixture
def patch_identity(monkeypatch):
    upsert = AsyncMock()
    monkeypatch.setattr(
        orchestrator.channel_identities, "upsert_identity", upsert
    )
    return upsert


@pytest.fixture
def patch_central(monkeypatch):
    run = AsyncMock(
        return_value=SimpleNamespace(output=Reply(text="agent reply"))
    )
    monkeypatch.setattr(orchestrator.central_agent, "run", run)
    return run


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
    patch_inbox, patch_ledger, patch_identity, patch_central, patch_registry
):
    msg = _inbound("hi there")
    resolved_at = datetime.now(timezone.utc)
    patch_ledger.resolved.return_value = [
        _task(customer_context="vendor confirmed", resolved_at=resolved_at)
    ]
    # Mirror real Redis: peek returns whatever was just enqueued.
    patch_inbox.peek.return_value = [
        {"type": "user_message", "payload": {"text": "hi there"}}
    ]

    await orchestrator.handle_inbound(msg)

    patch_inbox.acquire.assert_called_once()
    patch_identity.assert_awaited_once()
    patch_inbox.enqueue.assert_called_once()
    patch_ledger.pending.assert_awaited_once_with(_BIZ_ID, _CUST_ID)
    patch_ledger.resolved.assert_awaited_once_with(_BIZ_ID, _CUST_ID, None)
    patch_central.assert_awaited_once()
    prompt_arg = patch_central.await_args.args[0]
    assert "hi there" in prompt_arg
    assert "vendor confirmed" in prompt_arg
    patch_registry.channel.send.assert_awaited_once_with(msg.identity, "agent reply")
    patch_inbox.drain.assert_called_once_with(_BIZ_ID, _CUST_ID)
    patch_inbox.set_cursor.assert_called_once_with(_BIZ_ID, _CUST_ID, resolved_at)
    patch_inbox.release.assert_called_once()


@pytest.mark.asyncio
async def test_lock_contention_enqueues_without_running_central(
    patch_inbox, patch_ledger, patch_identity, patch_central, patch_registry
):
    patch_inbox.acquire.return_value = False

    await orchestrator.handle_inbound(_inbound())

    patch_inbox.enqueue.assert_called_once()
    patch_central.assert_not_awaited()
    patch_registry.channel.send.assert_not_awaited()
    patch_inbox.drain.assert_not_called()
    patch_identity.assert_not_awaited()
    # Lock was never held by us, so we must not release it.
    patch_inbox.release.assert_not_called()


@pytest.mark.asyncio
async def test_drain_skipped_when_send_fails(
    patch_inbox, patch_ledger, patch_identity, patch_central, patch_registry
):
    patch_registry.channel.send.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await orchestrator.handle_inbound(_inbound())

    patch_central.assert_awaited_once()
    patch_inbox.drain.assert_not_called()
    patch_inbox.set_cursor.assert_not_called()
    # Lock must always release.
    patch_inbox.release.assert_called_once()


@pytest.mark.asyncio
async def test_no_resolved_means_cursor_untouched(
    patch_inbox, patch_ledger, patch_identity, patch_central, patch_registry
):
    patch_ledger.resolved.return_value = []

    await orchestrator.handle_inbound(_inbound())

    patch_inbox.drain.assert_called_once()
    patch_inbox.set_cursor.assert_not_called()


def test_build_prompt_contains_all_sections():
    pending = [_task(party="vendor-a", dispatch_prompt="confirm stock")]
    resolved = [_task(party="vendor-b", customer_context="shipped today")]
    items = [
        {"type": "user_message", "payload": {"text": "where is my order?"}},
        {"type": "system_event", "payload": {"summary": "vendor pinged"}},
    ]

    prompt = orchestrator._build_prompt(items, pending, resolved)

    assert "Pending outbound tasks" in prompt
    assert "vendor-a: confirm stock" in prompt
    assert "Recently resolved outbound tasks" in prompt
    assert "vendor-b: shipped today" in prompt
    assert "Customer messages this turn:" in prompt
    assert "- where is my order?" in prompt
    assert "- (system) vendor pinged" in prompt


def test_whatsapp_webhook_invokes_orchestrator(monkeypatch):
    from backend.api.routers.webhooks import whatsapp as whatsapp_webhook

    captured: dict = {}

    async def fake_handle_inbound(msg: InboundMessage) -> None:
        captured["msg"] = msg

    fake_msg = _inbound("from webhook")
    fake_channel = SimpleNamespace(parse_inbound=MagicMock(return_value=fake_msg))
    monkeypatch.setattr(whatsapp_webhook.orchestrator, "handle_inbound", fake_handle_inbound)
    monkeypatch.setattr(whatsapp_webhook.registry, "get", lambda name: fake_channel)

    app = FastAPI()
    app.include_router(whatsapp_webhook.router)

    payload = {"entry": [{"changes": [{"value": {"sample": True}}]}]}
    with TestClient(app) as client:
        response = client.post("/webhooks/whatsapp", json=payload)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    fake_channel.parse_inbound.assert_called_once_with(payload)
    assert captured["msg"] is fake_msg
