"""Tests for the channel handler.

Mocks the channel and the channel_identities accessor — no DB needed.
"""

from datetime import datetime, timedelta, timezone
from typing import ClassVar
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.chatbot.channels import handler
from backend.chatbot.channels.base import (
    Channel,
    ChannelIdentity,
    InboundMessage,
    WindowPolicy,
)
from backend.db.outbound_ledger import OutboundTaskRow


class _FakeChannel(Channel):
    name: ClassVar[str] = "fake"

    def __init__(self, policy: WindowPolicy) -> None:
        self._policy = policy
        self.send = AsyncMock()
        self.send_template = AsyncMock()

    def parse_inbound(self, raw: dict) -> InboundMessage:  # pragma: no cover
        raise NotImplementedError

    async def send(  # noqa: F811 — AsyncMock overrides on __init__
        self, identity: ChannelIdentity, text: str
    ) -> None:  # pragma: no cover
        raise NotImplementedError

    async def send_template(  # noqa: F811
        self, identity: ChannelIdentity, template: str, vars: dict
    ) -> None:  # pragma: no cover
        raise NotImplementedError

    def window_policy(self) -> WindowPolicy:
        return self._policy


def _make_task(customer_context: str | None = "customer ready") -> OutboundTaskRow:
    now = datetime.now(timezone.utc)
    return OutboundTaskRow(
        task_key="tk-1",
        business_id=uuid4(),
        customer_id=uuid4(),
        party="vendor-x",
        initiated_by="customer",
        dispatch_prompt="ask vendor",
        state="succeeded",
        customer_context=customer_context,
        system_context=None,
        dispatched_at=now,
        resolved_at=now,
        timeout_at=now + timedelta(minutes=5),
    )


def _make_identity(last_inbound_at: datetime | None) -> ChannelIdentity:
    return ChannelIdentity(
        business_id=str(uuid4()),
        customer_id=str(uuid4()),
        channel="fake",
        channel_user_id="user-1",
        last_inbound_at=last_inbound_at,
    )


@pytest.fixture
def patch_get_identity(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(handler.channel_identities, "get_identity", mock)
    return mock


@pytest.mark.asyncio
async def test_in_window_resolution_does_not_send(patch_get_identity):
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    patch_get_identity.return_value = _make_identity(last_inbound_at=recent)
    channel = _FakeChannel(
        WindowPolicy(
            has_window=True, window_hours=24, out_of_window_behavior="template"
        )
    )

    await handler.handle_resolution(_make_task(), channel)

    channel.send.assert_not_called()
    channel.send_template.assert_not_called()


@pytest.mark.asyncio
async def test_out_of_window_template_sends_template(patch_get_identity):
    stale = datetime.now(timezone.utc) - timedelta(hours=48)
    patch_get_identity.return_value = _make_identity(last_inbound_at=stale)
    channel = _FakeChannel(
        WindowPolicy(
            has_window=True, window_hours=24, out_of_window_behavior="template"
        )
    )

    task = _make_task(customer_context="order shipped")
    await handler.handle_resolution(task, channel)

    channel.send.assert_not_called()
    channel.send_template.assert_awaited_once()
    call = channel.send_template.await_args
    assert call.kwargs["template"] == handler._DEFAULT_TEMPLATE
    assert call.kwargs["vars"] == {"summary": "order shipped"}
    assert call.args[0] is patch_get_identity.return_value


@pytest.mark.asyncio
async def test_out_of_window_drop_does_nothing(patch_get_identity):
    stale = datetime.now(timezone.utc) - timedelta(hours=48)
    patch_get_identity.return_value = _make_identity(last_inbound_at=stale)
    channel = _FakeChannel(
        WindowPolicy(
            has_window=True, window_hours=24, out_of_window_behavior="drop"
        )
    )

    await handler.handle_resolution(_make_task(), channel)

    channel.send.assert_not_called()
    channel.send_template.assert_not_called()


@pytest.mark.asyncio
async def test_out_of_window_queue_defers(patch_get_identity):
    stale = datetime.now(timezone.utc) - timedelta(hours=48)
    patch_get_identity.return_value = _make_identity(last_inbound_at=stale)
    channel = _FakeChannel(
        WindowPolicy(
            has_window=True, window_hours=24, out_of_window_behavior="queue"
        )
    )

    await handler.handle_resolution(_make_task(), channel)

    channel.send.assert_not_called()
    channel.send_template.assert_not_called()


@pytest.mark.asyncio
async def test_no_window_channel_sends_directly(patch_get_identity):
    patch_get_identity.return_value = _make_identity(last_inbound_at=None)
    channel = _FakeChannel(
        WindowPolicy(
            has_window=False, window_hours=None, out_of_window_behavior="drop"
        )
    )

    task = _make_task(customer_context="delivered")
    await handler.handle_resolution(task, channel)

    channel.send.assert_awaited_once()
    assert channel.send.await_args.args[0] is patch_get_identity.return_value
    assert channel.send.await_args.args[1] == "delivered"
    channel.send_template.assert_not_called()


@pytest.mark.asyncio
async def test_no_window_with_empty_customer_context_sends_empty(patch_get_identity):
    patch_get_identity.return_value = _make_identity(last_inbound_at=None)
    channel = _FakeChannel(
        WindowPolicy(
            has_window=False, window_hours=None, out_of_window_behavior="drop"
        )
    )

    task = _make_task(customer_context=None)
    await handler.handle_resolution(task, channel)

    channel.send.assert_awaited_once_with(patch_get_identity.return_value, "")


@pytest.mark.asyncio
async def test_no_identity_is_noop(patch_get_identity):
    patch_get_identity.return_value = None
    channel = _FakeChannel(
        WindowPolicy(
            has_window=True, window_hours=24, out_of_window_behavior="template"
        )
    )

    await handler.handle_resolution(_make_task(), channel)

    channel.send.assert_not_called()
    channel.send_template.assert_not_called()


@pytest.mark.asyncio
async def test_identity_without_last_inbound_is_out_of_window(patch_get_identity):
    patch_get_identity.return_value = _make_identity(last_inbound_at=None)
    channel = _FakeChannel(
        WindowPolicy(
            has_window=True, window_hours=24, out_of_window_behavior="template"
        )
    )

    await handler.handle_resolution(_make_task(), channel)

    channel.send_template.assert_awaited_once()
