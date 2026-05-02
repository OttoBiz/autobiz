"""Tests for the HTTP channel and its webhook router.

Covers parse_inbound, queue-based send, and the end-to-end webhook flow
(POST /webhooks/http invoking orchestrator.handle_inbound) plus the SSE
stream delivering an outbound message to a subscriber.
"""

from __future__ import annotations

import os

# Importing the webhook router pulls in `orchestrator`, which pulls in `inbox`
# (Redis-backed). The Redis client wants a host/port at construction time, so
# we set harmless defaults before any backend.* import happens.
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "")

import json  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.chatbot.channels import registry  # noqa: E402
from backend.chatbot.channels.base import ChannelIdentity, InboundMessage  # noqa: E402
from backend.chatbot.channels.http import HTTPChannel  # noqa: E402


_BIZ_ID = str(uuid4())
_CUST_ID = str(uuid4())


@pytest.fixture
def http_channel() -> HTTPChannel:
    return HTTPChannel()


def test_parse_inbound_builds_identity_and_text(http_channel: HTTPChannel):
    raw = {
        "business_id": _BIZ_ID,
        "customer_id": _CUST_ID,
        "channel_user_id": "session-abc",
        "text": "hello from browser",
    }

    msg = http_channel.parse_inbound(raw)

    assert isinstance(msg, InboundMessage)
    assert msg.text == "hello from browser"
    assert msg.identity.channel == "http"
    assert msg.identity.business_id == _BIZ_ID
    assert msg.identity.customer_id == _CUST_ID
    assert msg.identity.channel_user_id == "session-abc"
    assert msg.identity.last_inbound_at is not None
    assert msg.media == []
    assert msg.interactive is None


def test_parse_inbound_defaults_channel_user_id_to_customer_id(
    http_channel: HTTPChannel,
):
    raw = {
        "business_id": _BIZ_ID,
        "customer_id": _CUST_ID,
        "text": "hi",
    }

    msg = http_channel.parse_inbound(raw)

    assert msg.identity.channel_user_id == _CUST_ID


def test_parse_inbound_passes_through_interactive_payload(
    http_channel: HTTPChannel,
):
    raw = {
        "business_id": _BIZ_ID,
        "customer_id": _CUST_ID,
        "channel_user_id": "s1",
        "text": "Yes",
        "interactive": {"type": "button_reply", "id": "confirm_yes"},
    }

    msg = http_channel.parse_inbound(raw)

    assert msg.interactive == {"type": "button_reply", "id": "confirm_yes"}


@pytest.mark.asyncio
async def test_send_enqueues_on_recipient_queue(http_channel: HTTPChannel):
    identity = ChannelIdentity(
        business_id=_BIZ_ID,
        customer_id=_CUST_ID,
        channel="http",
        channel_user_id="session-abc",
        last_inbound_at=None,
    )

    await http_channel.send(identity, "agent reply")

    queue = http_channel.subscribe("session-abc")
    assert queue.get_nowait() == "agent reply"


@pytest.mark.asyncio
async def test_send_template_renders_to_tagged_string(http_channel: HTTPChannel):
    identity = ChannelIdentity(
        business_id=_BIZ_ID,
        customer_id=_CUST_ID,
        channel="http",
        channel_user_id="session-abc",
        last_inbound_at=None,
    )

    await http_channel.send_template(identity, "order_update", {"status": "shipped"})

    queue = http_channel.subscribe("session-abc")
    rendered = queue.get_nowait()
    assert "[template:order_update]" in rendered
    assert "shipped" in rendered


def test_subscribe_is_idempotent_per_recipient(http_channel: HTTPChannel):
    q1 = http_channel.subscribe("session-abc")
    q2 = http_channel.subscribe("session-abc")
    q3 = http_channel.subscribe("session-xyz")

    assert q1 is q2
    assert q1 is not q3


def test_window_policy_has_no_window(http_channel: HTTPChannel):
    policy = http_channel.window_policy()
    assert policy.has_window is False
    assert policy.window_hours is None


def test_module_import_registers_channel():
    # Importing the module installs the channel in the registry.
    import backend.chatbot.channels.http as http_module  # noqa: F401

    assert registry.get("http").name == "http"


def test_http_webhook_ingests_via_unified_inbox(monkeypatch):
    from backend.api.routers.webhooks import http as http_webhook

    fake_msg = InboundMessage(
        identity=ChannelIdentity(
            business_id=_BIZ_ID,
            customer_id=_CUST_ID,
            channel="http",
            channel_user_id="session-abc",
            last_inbound_at=None,
        ),
        text="hi",
        media=[],
        raw={},
        received_at=datetime.now(timezone.utc),
    )
    fake_channel = SimpleNamespace(parse_inbound=MagicMock(return_value=fake_msg))
    ingest_mock = MagicMock(return_value=True)
    monkeypatch.setattr(http_webhook.inbox, "ingest", ingest_mock)
    monkeypatch.setattr(http_webhook.registry, "get", lambda name: fake_channel)

    app = FastAPI()
    app.include_router(http_webhook.router)

    payload = {
        "business_id": _BIZ_ID,
        "customer_id": _CUST_ID,
        "channel_user_id": "session-abc",
        "text": "hi",
    }
    with TestClient(app) as client:
        response = client.post("/webhooks/http", json=payload)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    fake_channel.parse_inbound.assert_called_once_with(payload)
    ingest_mock.assert_called_once()
    party = ingest_mock.call_args.args[0]
    item = ingest_mock.call_args.args[1]
    assert party.kind == "customer"
    assert party.business_id == _BIZ_ID
    assert party.party_id == _CUST_ID
    assert item["payload"]["text"] == "hi"


@pytest.mark.asyncio
async def test_http_stream_emits_queued_message(monkeypatch):
    """SSE generator pulls a message off the recipient's queue and frames it.

    Tested by invoking the endpoint directly and iterating the
    StreamingResponse's body. A fake Request flips to "disconnected" once
    the first frame has been pulled, so the generator cleanly terminates.
    """
    from backend.api.routers.webhooks import http as http_webhook

    channel = HTTPChannel()
    channel.subscribe("session-abc").put_nowait("agent reply")
    monkeypatch.setattr(http_webhook.registry, "get", lambda name: channel)

    disconnect_flag = {"value": False}

    class _FakeRequest:
        async def is_disconnected(self) -> bool:
            return disconnect_flag["value"]

    response = await http_webhook.http_stream("session-abc", _FakeRequest())
    body_iter = response.body_iterator

    first_chunk = await body_iter.__anext__()
    # StreamingResponse emits bytes; decode for easy parsing.
    if isinstance(first_chunk, bytes):
        first_chunk = first_chunk.decode("utf-8")
    assert first_chunk.startswith("data: ")
    payload_str = first_chunk[len("data: ") :].strip()
    assert json.loads(payload_str) == {"text": "agent reply"}

    # Signal disconnect so the generator exits on its next loop iteration.
    disconnect_flag["value"] = True
    with pytest.raises(StopAsyncIteration):
        await body_iter.__anext__()
