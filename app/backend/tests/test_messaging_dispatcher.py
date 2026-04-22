"""Tests for the messaging dispatcher.

Two paths:
  - `dispatch_to_customer` always sends plain text via `channel.send`.
  - `dispatch_to_party` wraps text in a WhatsApp Flow (with `task_key` as
    `flow_token`) when the channel is whatsapp and a Flow ID is configured;
    otherwise it falls back to text + `[Ref: <task_key>]`.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.chatbot.channels.base import ChannelIdentity
from backend.chatbot.channels.whatsapp_messages import Flow
from backend.chatbot.messaging import dispatcher
from backend.chatbot.messaging.reply import Reply
from backend.config import config


def _identity() -> ChannelIdentity:
    return ChannelIdentity(
        business_id="biz",
        customer_id="cust",
        channel="whatsapp",
        channel_user_id="+15550001111",
        last_inbound_at=None,
    )


def _channel(name: str = "whatsapp") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        send=AsyncMock(),
        send_flow=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_dispatch_to_customer_sends_plain_text():
    channel = _channel()

    await dispatcher.dispatch_to_customer(channel, _identity(), Reply(text="hello"))

    channel.send.assert_awaited_once()
    _identity_arg, text = channel.send.await_args.args
    assert text == "hello"
    channel.send_flow.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_to_party_wraps_in_flow_with_task_key(monkeypatch):
    monkeypatch.setattr(config, "FLOW_OUTBOUND_TICKET_ID", "FLOW_OUT_42")
    monkeypatch.setattr(config, "FLOW_OUTBOUND_TICKET_SCREEN", "OUTBOUND_TICKET")
    channel = _channel()
    reply = Reply(text="When can you ship order #123?")

    await dispatcher.dispatch_to_party(
        channel, _identity(), reply, task_key="tk-abc"
    )

    channel.send_flow.assert_awaited_once()
    _identity_arg, flow = channel.send_flow.await_args.args
    assert isinstance(flow, Flow)
    assert flow.flow_id == "FLOW_OUT_42"
    assert flow.flow_token == "tk-abc"
    assert flow.body == "When can you ship order #123?"
    assert flow.screen == "OUTBOUND_TICKET"
    assert flow.data == {"task_key": "tk-abc", "context": reply.text}
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_to_party_truncates_long_body_but_keeps_full_context(monkeypatch):
    monkeypatch.setattr(config, "FLOW_OUTBOUND_TICKET_ID", "FLOW_OUT_42")
    long_text = "x" * 2000
    channel = _channel()

    await dispatcher.dispatch_to_party(
        channel, _identity(), Reply(text=long_text), task_key="tk-long"
    )

    _identity_arg, flow = channel.send_flow.await_args.args
    assert len(flow.body) == 1024
    # Full text survives in `data["context"]` so the Flow screen can render it.
    assert flow.data["context"] == long_text


@pytest.mark.asyncio
async def test_dispatch_to_party_falls_back_to_text_when_flow_unconfigured(monkeypatch):
    monkeypatch.setattr(config, "FLOW_OUTBOUND_TICKET_ID", "")
    channel = _channel()

    await dispatcher.dispatch_to_party(
        channel, _identity(), Reply(text="hi vendor"), task_key="tk-99"
    )

    channel.send.assert_awaited_once()
    _identity_arg, text = channel.send.await_args.args
    assert text == "hi vendor\n\n[Ref: tk-99]"
    channel.send_flow.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_to_party_falls_back_to_text_for_non_whatsapp(monkeypatch):
    monkeypatch.setattr(config, "FLOW_OUTBOUND_TICKET_ID", "FLOW_OUT_42")
    channel = _channel(name="telegram")

    await dispatcher.dispatch_to_party(
        channel, _identity(), Reply(text="ping"), task_key="tk-tg"
    )

    channel.send.assert_awaited_once()
    _identity_arg, text = channel.send.await_args.args
    assert text == "ping\n\n[Ref: tk-tg]"
    channel.send_flow.assert_not_awaited()
