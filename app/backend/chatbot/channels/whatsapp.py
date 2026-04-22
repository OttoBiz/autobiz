import asyncio
import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import ClassVar, Optional
from urllib.parse import parse_qs

import requests
from dotenv import load_dotenv

from backend.chatbot.channels import registry
from backend.chatbot.channels.base import (
    Channel,
    ChannelIdentity,
    InboundMessage,
    MediaAttachment,
    WindowPolicy,
)
from backend.config import config

load_dotenv()

logger = logging.getLogger(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
APP_SECRET = os.getenv("APP_SECRET", "")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "") or config.WHATSAPP_API_KEY

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


class WhatsappBot:
    """Thin client for WhatsApp Cloud API verify + send."""

    def __init__(
        self,
        page_access_token: Optional[str] = None,
        app_secret: Optional[str] = None,
        verify_token: Optional[str] = None,
    ):
        self.page_access_token = page_access_token or PAGE_ACCESS_TOKEN
        self.app_secret = app_secret or APP_SECRET
        self.verify_token = verify_token or VERIFY_TOKEN

    def verify_webhook(self, request) -> str:
        query_params = parse_qs(str(request.query_params))
        mode = query_params.get("hub.mode")
        token = query_params.get("hub.verify_token")
        challenge = query_params.get("hub.challenge")

        if mode and token:
            if mode[0] == "subscribe" and token[0] == self.verify_token:
                return challenge[0] if challenge else ""
            return "Invalid verification token"
        return "Invalid request"

    def verify_signature(self, request_body: bytes, signature: str) -> bool:
        if not self.app_secret:
            logger.warning("APP_SECRET not configured, skipping signature verification")
            return True
        if signature.startswith("sha256="):
            sha256 = hmac.new(
                self.app_secret.encode("utf-8"), request_body, hashlib.sha256
            ).hexdigest()
            return sha256 == signature[7:]
        if signature.startswith("sha1="):
            sha1 = hmac.new(
                self.app_secret.encode("utf-8"), request_body, hashlib.sha1
            ).hexdigest()
            return sha1 == signature[5:]
        return False

    def send_message(
        self, phone_number_id: str, recipient_id: str, message: str
    ) -> bool:
        if not self.page_access_token or not phone_number_id:
            logger.warning("WhatsApp credentials not configured")
            return False

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_id,
            "type": "text",
            "text": {"preview_url": True, "body": message},
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.page_access_token}",
        }

        try:
            response = requests.post(
                f"https://graph.facebook.com/v18.0/{phone_number_id}/messages",
                json=payload,
                headers=headers,
                timeout=10,
            )
            if response.status_code != 200:
                logger.error(
                    "Failed to send WhatsApp message: %s - %s",
                    response.status_code,
                    response.text,
                )
                return False
            return True
        except Exception as exc:
            logger.error("Error sending WhatsApp message: %s", exc)
            return False


_whatsapp_bot = WhatsappBot()


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
