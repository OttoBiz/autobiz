import asyncio
from datetime import datetime, timezone
from typing import ClassVar

import requests

from backend.chatbot.channels import registry
from backend.chatbot.channels.base import (
    Channel,
    ChannelIdentity,
    InboundMessage,
    MediaAttachment,
    WindowPolicy,
)
from backend.whatsapp.utils import whatsapp as _whatsapp_bot

_MEDIA_KINDS: tuple[str, ...] = ("image", "audio", "video", "document")


def _extract_value(raw: dict) -> dict:
    entry = raw.get("entry", [{}])[0]
    for change in entry.get("changes", []):
        value = change.get("value")
        if value and not value.get("statuses"):
            return value
    return {}


def _extract_media(message: dict) -> list[MediaAttachment]:
    attachments: list[MediaAttachment] = []
    for kind in _MEDIA_KINDS:
        payload = message.get(kind)
        if not payload:
            continue
        attachments.append(
            MediaAttachment(
                kind=kind,  # type: ignore[arg-type]
                url=None,
                mime_type=payload.get("mime_type"),
            )
        )
    return attachments


class WhatsappChannel(Channel):
    name: ClassVar[str] = "whatsapp"

    def parse_inbound(self, raw: dict) -> InboundMessage:
        value = _extract_value(raw)
        metadata = value["metadata"]
        message = value["messages"][0]

        business_id = metadata["phone_number_id"]
        customer_id = message["from"]
        text = message.get("text", {}).get("body") if message.get("text") else None

        identity = ChannelIdentity(
            business_id=business_id,
            customer_id=customer_id,
            channel=self.name,
            channel_user_id=customer_id,
            last_inbound_at=datetime.now(timezone.utc),
        )
        return InboundMessage(
            identity=identity,
            text=text,
            media=_extract_media(message),
            raw=raw,
            received_at=datetime.now(timezone.utc),
        )

    async def send(self, identity: ChannelIdentity, text: str) -> None:
        await asyncio.to_thread(
            _whatsapp_bot.send_message,
            identity.business_id,
            identity.channel_user_id,
            text,
        )

    async def send_template(
        self, identity: ChannelIdentity, template: str, vars: dict
    ) -> None:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": identity.channel_user_id,
            "type": "template",
            "template": {
                "name": template,
                "language": {"code": vars.get("language", "en_US")},
                "components": vars.get("components", []),
            },
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_whatsapp_bot.page_access_token}",
        }
        url = f"https://graph.facebook.com/v18.0/{identity.business_id}/messages"
        await asyncio.to_thread(
            requests.post, url, json=payload, headers=headers, timeout=10
        )

    def window_policy(self) -> WindowPolicy:
        return WindowPolicy(
            has_window=True, window_hours=24, out_of_window_behavior="template"
        )


registry.register(WhatsappChannel())
