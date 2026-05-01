"""Tests for the WhatsApp webhook's `case "contact"` branch.

Verifies that inbound messages from a known contact are enqueued onto the
per-contact debounced inbox and that schedule_drain is wired to the agent
adapter, without firing the actual debounce window.
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
from uuid import UUID, uuid4  # noqa: E402

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.chatbot.channels.base import ChannelIdentity, InboundMessage  # noqa: E402


def _contact_inbound(text: str | None = "vendor reply") -> InboundMessage:
    return InboundMessage(
        identity=ChannelIdentity(
            business_id="placeholder",
            customer_id="placeholder",
            channel="whatsapp",
            channel_user_id="vendor-wa-1",
            channel_business_id="phone-id-1",
            last_inbound_at=datetime.now(timezone.utc),
        ),
        text=text,
        media=[],
        raw={"sample": True},
        received_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def app_client(monkeypatch):
    """Build a FastAPI app with the whatsapp router and standard stubs.

    Caller can pre-stub `parse_inbound` / `resolve_inbound_sender` /
    `contact_inbox` before the request fires.
    """
    from backend.api.routers.webhooks import whatsapp as whatsapp_webhook

    app = FastAPI()
    app.include_router(whatsapp_webhook.router)
    return SimpleNamespace(
        module=whatsapp_webhook,
        client=TestClient(app),
    )


def test_contact_branch_enqueues_message_and_schedules_drain(app_client, monkeypatch):
    from backend.chatbot.channels.whatsapp_resolver import InboundSender

    biz_id = uuid4()
    contact_id = uuid4()

    fake_msg = _contact_inbound("yes, 5 in stock")
    fake_channel = SimpleNamespace(parse_inbound=MagicMock(return_value=fake_msg))

    async def fake_resolve(phone_number_id, wa_id):
        return InboundSender(
            kind="contact",
            business_id=biz_id,
            contact_id=contact_id,
            contact_name="Vendor X",
            contact_role="vendor",
        )

    enqueue_mock = MagicMock()
    schedule_mock = AsyncMock()

    monkeypatch.setattr(app_client.module.registry, "get", lambda name: fake_channel)
    monkeypatch.setattr(app_client.module, "resolve_inbound_sender", fake_resolve)
    monkeypatch.setattr(app_client.module.contact_inbox, "enqueue", enqueue_mock)
    monkeypatch.setattr(
        app_client.module.contact_inbox, "schedule_drain", schedule_mock
    )

    response = app_client.client.post(
        "/webhooks/whatsapp",
        json={"entry": [{"changes": [{"value": {"sample": True}}]}]},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    fake_channel.parse_inbound.assert_called_once()
    enqueue_mock.assert_called_once_with(str(biz_id), str(contact_id), "yes, 5 in stock")
    schedule_mock.assert_awaited_once()
    sched_args = schedule_mock.await_args.args
    assert sched_args[0] == str(biz_id)
    assert sched_args[1] == str(contact_id)
    # Third arg is the runner adapter — module-level _run_contact_reply.
    assert sched_args[2] is app_client.module._run_contact_reply


def test_contact_branch_returns_ignored_when_text_is_empty(app_client, monkeypatch):
    from backend.chatbot.channels.whatsapp_resolver import InboundSender

    biz_id = uuid4()
    contact_id = uuid4()

    fake_msg = _contact_inbound(None)  # no text — e.g. media-only inbound
    fake_channel = SimpleNamespace(parse_inbound=MagicMock(return_value=fake_msg))

    async def fake_resolve(phone_number_id, wa_id):
        return InboundSender(
            kind="contact",
            business_id=biz_id,
            contact_id=contact_id,
            contact_name="Vendor X",
            contact_role="vendor",
        )

    enqueue_mock = MagicMock()
    schedule_mock = AsyncMock()

    monkeypatch.setattr(app_client.module.registry, "get", lambda name: fake_channel)
    monkeypatch.setattr(app_client.module, "resolve_inbound_sender", fake_resolve)
    monkeypatch.setattr(app_client.module.contact_inbox, "enqueue", enqueue_mock)
    monkeypatch.setattr(
        app_client.module.contact_inbox, "schedule_drain", schedule_mock
    )

    response = app_client.client.post(
        "/webhooks/whatsapp",
        json={"entry": [{"changes": [{"value": {"sample": True}}]}]},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "ignored": "contact_no_text"}
    enqueue_mock.assert_not_called()
    schedule_mock.assert_not_awaited()


def test_run_contact_reply_forwards_to_outbound(monkeypatch):
    """The `_run_contact_reply` adapter calls `outbound.deliver_contact_reply`
    with the same (biz, contact_id, messages) it received."""
    from backend.api.routers.webhooks import whatsapp as whatsapp_webhook

    deliver_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(whatsapp_webhook.outbound, "deliver_contact_reply", deliver_mock)

    import asyncio

    asyncio.run(whatsapp_webhook._run_contact_reply("biz1", "c1", ["yes", "5"]))

    deliver_mock.assert_awaited_once_with("biz1", "c1", ["yes", "5"])
