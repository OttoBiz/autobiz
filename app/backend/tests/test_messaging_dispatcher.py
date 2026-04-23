"""Tests for the messaging dispatcher.

- `dispatch_to_customer` always sends plain text via `channel.send`.
- `dispatch_to_party` sends text plus a `[Ref: <task_key>]` marker so the
  vendor's reply can be routed back. Per-tenant Flow wrapping is layered on
  top later via the credentials store.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.chatbot.channels.base import ChannelIdentity
from backend.chatbot.messaging import dispatcher


def _identity() -> ChannelIdentity:
    return ChannelIdentity(
        business_id="biz",
        customer_id="cust",
        channel="whatsapp",
        channel_user_id="+15550001111",
        last_inbound_at=None,
    )


def _channel() -> SimpleNamespace:
    return SimpleNamespace(name="whatsapp", send=AsyncMock())


@pytest.mark.asyncio
async def test_dispatch_to_customer_sends_plain_text():
    channel = _channel()

    await dispatcher.dispatch_to_customer(channel, _identity(), "hello")

    channel.send.assert_awaited_once()
    _identity_arg, text = channel.send.await_args.args
    assert text == "hello"


@pytest.mark.asyncio
async def test_dispatch_to_party_appends_task_ref_marker():
    channel = _channel()

    await dispatcher.dispatch_to_party(
        channel, _identity(), "When can you ship?", task_key="tk-abc"
    )

    channel.send.assert_awaited_once()
    _identity_arg, text = channel.send.await_args.args
    assert text == "When can you ship?\n\n[Ref: tk-abc]"
