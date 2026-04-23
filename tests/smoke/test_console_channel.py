"""Unit tests for the ConsoleChannel smoke adapter."""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402

from backend.chatbot.channels import registry  # noqa: E402
from backend.chatbot.channels.base import ChannelIdentity  # noqa: E402

from tests.smoke.console_channel import ConsoleChannel, install  # noqa: E402


def _identity(recipient: str = "+15550001") -> ChannelIdentity:
    return ChannelIdentity(
        business_id="b" * 32,
        customer_id="c" * 32,
        channel="console",
        channel_user_id=recipient,
        last_inbound_at=None,
    )


@pytest.mark.asyncio
async def test_send_lands_on_subscriber_queue():
    channel = ConsoleChannel()
    queue = channel.subscribe("+15550001")

    await channel.send(_identity("+15550001"), "hello")

    assert await asyncio.wait_for(queue.get(), timeout=0.1) == "hello"


@pytest.mark.asyncio
async def test_two_recipients_get_independent_queues():
    channel = ConsoleChannel()
    cust = channel.subscribe("+15550001")
    vendor = channel.subscribe("vendor-1")

    await channel.send(_identity("+15550001"), "to customer")
    await channel.send(_identity("vendor-1"), "to vendor")

    assert await asyncio.wait_for(cust.get(), timeout=0.1) == "to customer"
    assert await asyncio.wait_for(vendor.get(), timeout=0.1) == "to vendor"
    assert cust.empty()
    assert vendor.empty()


@pytest.mark.asyncio
async def test_send_template_renders_into_queue():
    channel = ConsoleChannel()
    queue = channel.subscribe("+15550001")

    await channel.send_template(
        _identity("+15550001"), template="status_update", vars={"summary": "ok"}
    )

    msg = await asyncio.wait_for(queue.get(), timeout=0.1)
    assert "[template:status_update]" in msg
    assert "ok" in msg


def test_parse_inbound_is_unsupported():
    channel = ConsoleChannel()
    with pytest.raises(NotImplementedError):
        channel.parse_inbound({"any": "payload"})


def test_window_policy_has_no_window():
    policy = ConsoleChannel().window_policy()
    assert policy.has_window is False


def test_install_registers_channel_and_resolver():
    channel = install()
    assert registry.get("console") is channel

    # Calling install twice returns the same instance (idempotent).
    again = install()
    assert again is channel


@pytest.mark.asyncio
async def test_install_resolver_returns_channel_for_any_customer():
    channel = install()
    resolved = await registry.get_for_customer("any-biz", "any-cust")
    assert resolved is channel
