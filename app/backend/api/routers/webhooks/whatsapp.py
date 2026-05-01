"""WhatsApp webhook — verifies signature, parses inbound, hands to orchestrator.

GET handles Meta's verification handshake. POST verifies the X-Hub-Signature-256
header against the raw body, parses the payload via the registered channel,
classifies the sender via `resolve_inbound_sender`, then forks: unknown
tenants and owner self-messages are dropped with 200, contact replies are
deferred (also 200), and customer messages get their IDs swapped for UUIDs
and dispatched to the orchestrator.

Importing `chatbot.channels.whatsapp` registers the channel as a side effect.
"""

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

import backend.chatbot.channels.whatsapp  # noqa: F401  triggers channel registration
from backend.chatbot import orchestrator
from backend.chatbot.channels import registry
from backend.chatbot.channels.base import ChannelIdentity
from backend.chatbot.channels.whatsapp import NonMessageEvent, _whatsapp_bot
from backend.chatbot.channels.whatsapp_resolver import (
    resolve_inbound_sender,
    resolve_or_create_customer_by_phone,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/whatsapp")
def whatsapp_verify(request: Request) -> PlainTextResponse:
    body = _whatsapp_bot.verify_webhook(request)
    # Meta accepts the handshake by echoing `hub.challenge` verbatim. Any
    # other body means the token/mode didn't match — surface that as 403 so
    # bad probes don't appear successful in logs and dashboards.
    status = 200 if body == request.query_params.get("hub.challenge") else 403
    return PlainTextResponse(body, status_code=status)


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request) -> dict:
    raw_body = await request.body()
    signature = request.headers.get("x-hub-signature-256") or request.headers.get(
        "x-hub-signature", ""
    )
    if not _whatsapp_bot.verify_signature(raw_body, signature):
        raise HTTPException(status_code=403, detail="invalid signature")

    try:
        payload = json.loads(raw_body)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid json")

    channel = registry.get("whatsapp")
    try:
        msg = channel.parse_inbound(payload)
    except NonMessageEvent as exc:
        logger.info("ignoring non-message webhook: %s", exc)
        # 200 so Meta stops retrying — status callbacks (sent/delivered/read)
        # and template status events legitimately have no user message.
        return {"ok": True, "ignored": "non_message_event"}
    # `parse_inbound` stuffs WA-native IDs into the identity; classify them
    # against businesses+contacts before deciding what to do.
    phone_number_id = msg.identity.channel_business_id
    wa_id = msg.identity.channel_user_id
    sender = await resolve_inbound_sender(phone_number_id, wa_id)

    match sender.kind:
        case "unknown_tenant":
            logger.warning(
                "dropping inbound for unknown tenant phone_number_id=%s",
                phone_number_id,
            )
            # 200 so Meta stops retrying — we don't own this number.
            return {"ok": True, "ignored": "unknown_tenant"}
        case "owner":
            logger.info(
                "ignoring owner self-message business=%s wa_id=%s",
                sender.business_id,
                wa_id,
            )
            return {"ok": True, "ignored": "owner_self_message"}
        case "contact":
            logger.info(
                "contact reply received (routing deferred) contact=%s name=%s",
                sender.contact_id,
                sender.contact_name,
            )
            return {"ok": True, "ignored": "contact_reply_deferred"}
        case "customer":
            customer_uuid = await resolve_or_create_customer_by_phone(wa_id)
            resolved_identity = ChannelIdentity(
                business_id=str(sender.business_id),
                customer_id=str(customer_uuid),
                channel="whatsapp",
                channel_user_id=wa_id,
                channel_business_id=phone_number_id,
                last_inbound_at=msg.identity.last_inbound_at,
            )
            msg = msg.model_copy(update={"identity": resolved_identity})
            await orchestrator.handle_inbound(msg)
            return {"ok": True}
