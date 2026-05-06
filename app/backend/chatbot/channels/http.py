"""HTTP channel — connects the orchestrator to a browser/JS frontend.

Inbound: the frontend POSTs `{business_id, customer_id, channel_user_id, text}`
to `/webhooks/http`; the router calls `parse_inbound` and hands the resulting
`InboundMessage` to the orchestrator.

Outbound: agent replies land on a per-recipient `asyncio.Queue` keyed by
`channel_user_id`. The `/webhooks/http/stream/{channel_user_id}` SSE endpoint
subscribes to that queue and pushes each message to the frontend as it is
produced. This mirrors the ConsoleChannel's queue-per-recipient pattern so
the smoke-harness routing convention (channel_user_id is the recipient
address) still holds.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import ClassVar

from backend.chatbot.channels import registry
from backend.chatbot.channels.base import (
    Channel,
    ChannelIdentity,
    InboundMessage,
    MediaAttachment,
    WindowPolicy,
)


class HTTPChannel(Channel):
    name: ClassVar[str] = "http"

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[str]] = {}

    def subscribe(self, recipient_id: str) -> asyncio.Queue[str]:
        """Get the outbound queue for a recipient, creating it if missing."""
        return self._queues.setdefault(recipient_id, asyncio.Queue())

    def parse_inbound(self, raw: dict) -> InboundMessage:
        business_id = raw["business_id"]
        customer_id = raw["customer_id"]
        channel_user_id = raw.get("channel_user_id") or customer_id
        text = raw.get("text")
        interactive = raw.get("interactive")
        # Frontend uploaders POST attachments as `[{kind, url, mime_type}, ...]`
        # alongside `text`. The route layer is responsible for hosting the URL
        # somewhere the model can fetch.
        media = [
            MediaAttachment(
                kind=m.get("kind"),
                url=m.get("url"),
                mime_type=m.get("mime_type"),
                media_id=m.get("media_id"),
            )
            for m in (raw.get("media") or [])
        ]

        identity = ChannelIdentity(
            business_id=business_id,
            customer_id=customer_id,
            channel=self.name,
            channel_user_id=channel_user_id,
            last_inbound_at=datetime.now(timezone.utc),
        )
        return InboundMessage(
            identity=identity,
            text=text,
            media=media,
            raw=raw,
            received_at=datetime.now(timezone.utc),
            interactive=interactive,
        )

    async def send(self, identity: ChannelIdentity, text: str) -> None:
        await self.subscribe(identity.channel_user_id).put(text)

    async def send_template(
        self,
        identity: ChannelIdentity,
        template: str,
        vars: dict | None = None,
    ) -> None:
        rendered = f"[template:{template}] {vars or {}}"
        await self.subscribe(identity.channel_user_id).put(rendered)

    def window_policy(self) -> WindowPolicy:
        # HTTP has no carrier-enforced window — the browser tab is either
        # connected or it isn't, and disconnects are the frontend's problem.
        return WindowPolicy(
            has_window=False, window_hours=None, out_of_window_behavior="drop"
        )


_http_channel = HTTPChannel()
registry.register(_http_channel)
