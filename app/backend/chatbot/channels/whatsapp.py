import asyncio
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, ClassVar, Optional, Union
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
from backend.chatbot.channels.whatsapp_messages import (
    ButtonMessage,
    Flow,
    ListMessage,
    Template,
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


def _extract_interactive(
    message: dict,
) -> tuple[str | None, dict | None]:
    """Return `(text, interactive)` for an interactive inbound message.

    Returns `(None, None)` for non-interactive messages so callers can chain
    without branching.
    """
    interactive = message.get("interactive")
    if not interactive:
        return None, None

    int_type = interactive.get("type")

    if int_type == "button_reply":
        reply = interactive.get("button_reply", {})
        return reply.get("title"), {
            "type": "button_reply",
            "id": reply.get("id"),
            "title": reply.get("title"),
        }

    if int_type == "list_reply":
        reply = interactive.get("list_reply", {})
        return reply.get("title"), {
            "type": "list_reply",
            "id": reply.get("id"),
            "title": reply.get("title"),
            "description": reply.get("description"),
        }

    if int_type == "nfm_reply":
        reply = interactive.get("nfm_reply", {})
        # `response_json` arrives as a JSON-encoded string; fall back to the
        # raw value if parsing fails so we don't lose data.
        raw_payload = reply.get("response_json")
        try:
            payload = json.loads(raw_payload) if raw_payload else {}
        except (ValueError, TypeError):
            payload = {"_raw": raw_payload}
        return "flow_response", {
            "type": "nfm_reply",
            "name": reply.get("name"),
            "body": reply.get("body"),
            "payload": payload,
        }

    return None, None


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


def _wa_sender(identity: "ChannelIdentity") -> str:
    """The Meta `phone_number_id` to use as sender. Prefer the channel-native
    field, fall back to `business_id` for compatibility with identities
    constructed before the split."""
    return identity.channel_business_id or identity.business_id


def _post_message(phone_number_id: str, payload: dict[str, Any]) -> dict:
    """Sync POST to the Cloud API messages endpoint. Returns parsed JSON."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_whatsapp_bot.page_access_token}",
    }
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    response = requests.post(url, json=payload, headers=headers, timeout=10)
    if response.status_code != 200:
        logger.error(
            "WhatsApp send failed: %s - %s", response.status_code, response.text
        )
    try:
        return response.json()
    except ValueError:
        return {"status_code": response.status_code, "text": response.text}


class WhatsappChannel(Channel):
    name: ClassVar[str] = "whatsapp"

    def parse_inbound(self, raw: dict) -> InboundMessage:
        """Parse a Meta payload into an InboundMessage.

        The returned identity carries WhatsApp-native IDs in
        `channel_business_id` (the Meta `phone_number_id`) and
        `channel_user_id` (the customer's `wa_id`). `business_id` and
        `customer_id` are placeholders here — the webhook route runs
        `whatsapp_resolver.resolve_identity` to swap in the matching
        internal UUIDs before handing off to the orchestrator.
        """
        value = _extract_value(raw)
        metadata = value["metadata"]
        message = value["messages"][0]

        phone_number_id = metadata["phone_number_id"]
        wa_id = message["from"]
        text = message.get("text", {}).get("body") if message.get("text") else None

        interactive_text, interactive = _extract_interactive(message)
        if interactive_text is not None:
            text = interactive_text

        identity = ChannelIdentity(
            business_id=phone_number_id,
            customer_id=wa_id,
            channel=self.name,
            channel_user_id=wa_id,
            channel_business_id=phone_number_id,
            last_inbound_at=datetime.now(timezone.utc),
        )
        return InboundMessage(
            identity=identity,
            text=text,
            media=_extract_media(message),
            raw=raw,
            received_at=datetime.now(timezone.utc),
            interactive=interactive,
        )

    async def send(self, identity: ChannelIdentity, text: str) -> None:
        # TODO: out-of-window fallback. The queue-based resolution path
        # (orchestrator.deliver_system_event → central → dispatch_to_customer)
        # calls this `send` unconditionally. WhatsApp rejects free-form text
        # when the customer is outside the 24h service window; in that case
        # we need to fall back to `send_template` with the generated text as
        # a template variable (window_policy().out_of_window_behavior ==
        # "template"). Check `identity.last_inbound_at` against
        # window_policy().window_hours and route to the template path when
        # expired. Today this only bites live WhatsApp traffic — ConsoleChannel
        # has has_window=False so the smoke TUI is unaffected.
        await asyncio.to_thread(
            _whatsapp_bot.send_message,
            identity.channel_business_id or identity.business_id,
            identity.channel_user_id,
            text,
        )

    async def send_template(
        self,
        identity: ChannelIdentity,
        template: Union[str, Template],
        vars: dict | None = None,
    ) -> dict:
        if isinstance(template, Template):
            payload = template.to_whatsapp_payload()
        else:
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "type": "template",
                "template": {
                    "name": template,
                    "language": {"code": (vars or {}).get("language", "en_US")},
                    "components": (vars or {}).get("components", []),
                },
            }
        payload["to"] = identity.channel_user_id
        return await asyncio.to_thread(_post_message, _wa_sender(identity), payload)

    async def send_buttons(
        self, identity: ChannelIdentity, msg: ButtonMessage
    ) -> dict:
        payload = msg.to_whatsapp_payload()
        payload["to"] = identity.channel_user_id
        return await asyncio.to_thread(_post_message, _wa_sender(identity), payload)

    async def send_list(self, identity: ChannelIdentity, msg: ListMessage) -> dict:
        payload = msg.to_whatsapp_payload()
        payload["to"] = identity.channel_user_id
        return await asyncio.to_thread(_post_message, _wa_sender(identity), payload)

    async def send_flow(self, identity: ChannelIdentity, flow: Flow) -> dict:
        payload = flow.to_whatsapp_payload()
        payload["to"] = identity.channel_user_id
        return await asyncio.to_thread(_post_message, _wa_sender(identity), payload)

    def window_policy(self) -> WindowPolicy:
        return WindowPolicy(
            has_window=True, window_hours=24, out_of_window_behavior="template"
        )


registry.register(WhatsappChannel())
