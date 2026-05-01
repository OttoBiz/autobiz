"""WhatsApp webhook — verifies signature, parses inbound, hands to orchestrator.

GET handles Meta's verification handshake. POST verifies the X-Hub-Signature-256
header against the raw body, parses the payload via the registered channel,
swaps WA-native IDs for internal UUIDs (`whatsapp_resolver.resolve_inbound`),
then dispatches to the orchestrator.

Importing `chatbot.channels.whatsapp` registers the channel as a side effect.
"""

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

import backend.chatbot.channels.whatsapp  # noqa: F401  triggers channel registration
from backend.chatbot import orchestrator
from backend.chatbot.channels import registry
from backend.chatbot.channels.whatsapp import NonMessageEvent, _whatsapp_bot
from backend.chatbot.channels.whatsapp_resolver import (
    UnknownWhatsAppBusiness,
    resolve_inbound,
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
    # `parse_inbound` returns an identity carrying WA-native IDs; resolve
    # them to internal UUIDs before the orchestrator touches the DB.
    try:
        msg = await resolve_inbound(msg)
    except UnknownWhatsAppBusiness as exc:
        logger.warning("dropping inbound for unknown business: %s", exc)
        # 200 so Meta stops retrying — we don't own this number.
        return {"ok": True, "ignored": "unknown_business"}

    await orchestrator.handle_inbound(msg)
    return {"ok": True}
