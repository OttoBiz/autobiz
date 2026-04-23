"""Console channel — in-process Channel impl for the smoke harness.

Replaces WhatsApp (or any real transport) so the TUI / scenario runner can
drive the orchestrator end-to-end without external services. Outbound sends
land on per-recipient asyncio.Queues; the TUI subscribes to those queues to
populate the Customer and Vendor panes.

Routing convention: `identity.channel_user_id` is the recipient address.
- Customer messages target the customer's own address.
- Vendor messages (from outbound.dispatch) target the `party` string the
  agent supplied — that's the vendor's "phone number" in our model.

The TUI doesn't need to know about ChannelIdentity internals; it just calls
`channel.subscribe(recipient_id)` and gets back an `asyncio.Queue[str]`.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from backend.chatbot.channels import registry
from backend.chatbot.channels.base import (
    Channel,
    ChannelIdentity,
    InboundMessage,
    WindowPolicy,
)


class ConsoleChannel(Channel):
    name: ClassVar[str] = "console"

    def __init__(self) -> None:
        # Per-recipient queues (subscribe() pattern) for callers that want a
        # single recipient's stream. The TUI prefers `outbox` because it
        # carries the full identity — needed to demux customer vs vendor
        # without knowing addresses upfront.
        self._queues: dict[str, asyncio.Queue[str]] = {}
        self.outbox: asyncio.Queue[tuple[ChannelIdentity, str]] = asyncio.Queue()

    def subscribe(self, recipient_id: str) -> asyncio.Queue[str]:
        """Get the outbound queue for a single recipient. Creates if missing."""
        return self._queues.setdefault(recipient_id, asyncio.Queue())

    def parse_inbound(self, raw: dict) -> InboundMessage:
        # The smoke harness builds InboundMessage directly and calls
        # orchestrator.handle_inbound — no webhook payload to parse.
        raise NotImplementedError(
            "ConsoleChannel does not parse webhook payloads; "
            "construct InboundMessage directly."
        )

    async def send(self, identity: ChannelIdentity, text: str) -> None:
        await self.subscribe(identity.channel_user_id).put(text)
        await self.outbox.put((identity, text))

    async def send_template(
        self,
        identity: ChannelIdentity,
        template: str,
        vars: dict | None = None,
    ) -> None:
        # Render templates as a tagged string for the smoke pane. Real channel
        # adapters fan out to a templating service; the harness just needs the
        # message visible.
        rendered = f"[template:{template}] {vars or {}}"
        await self.subscribe(identity.channel_user_id).put(rendered)
        await self.outbox.put((identity, rendered))

    def window_policy(self) -> WindowPolicy:
        # No 24h window in the harness — every send is deliverable.
        return WindowPolicy(
            has_window=False, window_hours=None, out_of_window_behavior="drop"
        )


def install() -> ConsoleChannel:
    """Register the ConsoleChannel and wire it as the identity resolver.

    Idempotent: re-installing returns the same channel instance so test
    setup/teardown doesn't accumulate registry entries.
    """
    existing = registry._REGISTRY.get(ConsoleChannel.name)  # type: ignore[attr-defined]
    if isinstance(existing, ConsoleChannel):
        channel = existing
    else:
        channel = ConsoleChannel()
        registry.register(channel)

    async def _resolve(business_id: str, customer_id: str) -> Channel:
        # In the harness there is exactly one channel; resolution is trivial.
        return channel

    registry.set_identity_resolver(_resolve)
    return channel
