"""HTTP channel router — inbound POST + SSE outbound stream for the frontend.

Importing `chatbot.channels.http` registers the channel as a side effect.

Endpoints:
- `POST /webhooks/http`              — inbound message from the frontend.
- `GET  /webhooks/http/stream/{id}`  — SSE stream of outbound messages for
                                       the given `channel_user_id`.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

import backend.chatbot.channels.http  # noqa: F401  triggers channel registration
from backend.chatbot import orchestrator
from backend.chatbot.channels import registry

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Server-side keep-alive for idle SSE connections. Browsers and proxies can
# silently drop a connection that has been quiet for too long; a periodic
# comment line resets that timer without adding noise to the event stream.
_SSE_HEARTBEAT_SECONDS = 15


@router.post("/http")
async def http_inbound(request: Request) -> dict:
    payload = await request.json()
    channel = registry.get("http")
    msg = channel.parse_inbound(payload)
    await orchestrator.handle_inbound(msg)
    return {"ok": True}


@router.get("/http/stream/{channel_user_id}")
async def http_stream(channel_user_id: str, request: Request) -> StreamingResponse:
    channel = registry.get("http")
    queue = channel.subscribe(channel_user_id)

    async def event_gen():
        while True:
            if await request.is_disconnected():
                return
            try:
                text = await asyncio.wait_for(
                    queue.get(), timeout=_SSE_HEARTBEAT_SECONDS
                )
            except asyncio.TimeoutError:
                # SSE comment line — clients ignore it; keeps the connection warm.
                yield ": ping\n\n"
                continue
            yield f"data: {json.dumps({'text': text})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")
