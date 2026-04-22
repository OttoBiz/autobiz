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
from backend.whatsapp.utils import whatsapp as _whatsapp_bot

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/whatsapp")
def whatsapp_verify(request: Request) -> PlainTextResponse:
    return PlainTextResponse(_whatsapp_bot.verify_webhook(request))


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request) -> dict:
    payload = await request.json()
    channel = registry.get("whatsapp")
    msg = channel.parse_inbound(payload)
    await orchestrator.handle_inbound(msg)
    return {"ok": True}
