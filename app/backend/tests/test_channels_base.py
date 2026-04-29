from datetime import datetime, timezone

import pytest

from backend.chatbot.channels import registry
from backend.chatbot.channels.base import (
    Channel,
    ChannelIdentity,
    InboundMessage,
    WindowPolicy,
)


class FakeChannel(Channel):
    name = "fake"

    def __init__(self) -> None:
        self.sent: list[tuple[ChannelIdentity, str]] = []
        self.templates: list[tuple[ChannelIdentity, str, dict]] = []

    def parse_inbound(self, raw: dict) -> InboundMessage:
        identity = ChannelIdentity(
            business_id=raw["business_id"],
            customer_id=raw["customer_id"],
            channel=self.name,
            channel_user_id=raw["channel_user_id"],
            last_inbound_at=None,
        )
        return InboundMessage(
            identity=identity,
            text=raw.get("text"),
            media=[],
            raw=raw,
            received_at=datetime.now(timezone.utc),
        )

    async def send(self, identity: ChannelIdentity, text: str) -> None:
        self.sent.append((identity, text))

    async def send_template(
        self, identity: ChannelIdentity, template: str, vars: dict
    ) -> None:
        self.templates.append((identity, template, vars))

    def window_policy(self) -> WindowPolicy:
        return WindowPolicy(
            has_window=False, window_hours=None, out_of_window_behavior="drop"
        )


@pytest.fixture(autouse=True)
def _reset_registry():
    saved_registry = dict(registry._REGISTRY)
    saved_resolver = registry._identity_resolver
    registry._REGISTRY.clear()
    registry._identity_resolver = None
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved_registry)
    registry._identity_resolver = saved_resolver


def test_register_and_get():
    fake = FakeChannel()
    registry.register(fake)
    assert registry.get("fake") is fake


def test_get_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        registry.get("missing")


@pytest.mark.asyncio
async def test_get_for_customer_returns_none_without_resolver():
    assert await registry.get_for_customer("biz", "cust") is None


@pytest.mark.asyncio
async def test_get_for_customer_uses_resolver():
    fake = FakeChannel()
    registry.register(fake)

    async def resolver(business_id: str, customer_id: str) -> Channel:
        return fake

    registry.set_identity_resolver(resolver)
    assert await registry.get_for_customer("biz", "cust") is fake


def test_channel_abc_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        Channel()  # type: ignore[abstract]


def test_partial_implementation_cannot_be_instantiated():
    class Incomplete(Channel):
        name = "incomplete"

        def parse_inbound(self, raw: dict) -> InboundMessage:
            raise NotImplementedError

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]
