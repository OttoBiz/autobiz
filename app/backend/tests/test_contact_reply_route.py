"""Tests for the WhatsApp webhook's `case "contact"` branch.

Verifies that inbound messages from a known contact are ingested onto the
unified vendor inbox via `conversations.inbox.ingest` with the vendor
Conversation's `drain` as the runner.
"""

from __future__ import annotations

import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "")

from datetime import datetime, timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402
from uuid import uuid4  # noqa: E402

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
        raw={"messages": [{"id": "wamid.XYZ"}]},
        received_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def app_client(monkeypatch):
    from backend.api.routers.webhooks import whatsapp as whatsapp_webhook

    app = FastAPI()
    app.include_router(whatsapp_webhook.router)
    return SimpleNamespace(
        module=whatsapp_webhook,
        client=TestClient(app),
    )


def test_contact_branch_ingests_via_unified_inbox(app_client, monkeypatch):
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

    ingest_mock = MagicMock(return_value=True)
    monkeypatch.setattr(app_client.module.registry, "get", lambda name: fake_channel)
    monkeypatch.setattr(app_client.module, "resolve_inbound_sender", fake_resolve)
    monkeypatch.setattr(app_client.module.inbox, "ingest", ingest_mock)

    response = app_client.client.post(
        "/webhooks/whatsapp",
        json={"entry": [{"changes": [{"value": {"sample": True}}]}]},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    fake_channel.parse_inbound.assert_called_once()
    ingest_mock.assert_called_once()
    args = ingest_mock.call_args.args
    kwargs = ingest_mock.call_args.kwargs
    party = args[0]
    item = args[1]
    assert party.kind == "vendor"
    assert party.business_id == str(biz_id)
    assert party.party_id == str(contact_id)
    assert item["type"] == "user_message"
    assert item["payload"]["text"] == "yes, 5 in stock"
    # Dedup id should be the wamid extracted from the raw payload.
    assert kwargs["dedup_id"] == "wamid.XYZ"
    assert callable(kwargs["runner"])


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

    ingest_mock = MagicMock(return_value=True)
    monkeypatch.setattr(app_client.module.registry, "get", lambda name: fake_channel)
    monkeypatch.setattr(app_client.module, "resolve_inbound_sender", fake_resolve)
    monkeypatch.setattr(app_client.module.inbox, "ingest", ingest_mock)

    response = app_client.client.post(
        "/webhooks/whatsapp",
        json={"entry": [{"changes": [{"value": {"sample": True}}]}]},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "ignored": "contact_no_content"}
    ingest_mock.assert_not_called()
