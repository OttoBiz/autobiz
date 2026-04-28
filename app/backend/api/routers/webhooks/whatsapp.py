"""WhatsApp webhook — parses inbound payloads and hands them to the orchestrator.

Mirrors the verification handshake from `backend/whatsapp/routers.py` so this
router can replace it. Importing `chatbot.channels.whatsapp` registers the
channel as a side effect.
"""

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

import backend.chatbot.channels.whatsapp  # noqa: F401  triggers channel registration
from backend.chatbot import orchestrator
from backend.chatbot.channels import registry
from backend.chatbot.channels.whatsapp import _whatsapp_bot

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
    payload = await request.json()
    channel = registry.get("whatsapp")
    msg = channel.parse_inbound(payload)
    await orchestrator.handle_inbound(msg)
    return {"ok": True}
