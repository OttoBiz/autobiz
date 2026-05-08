"""WhatsApp webhook — verifies signature, parses inbound, classifies sender.

GET handles Meta's verification handshake. POST verifies the X-Hub-Signature-256
header against the raw body, parses the payload via the registered channel,
classifies the sender via `resolve_inbound_sender`, then forks:
- unknown_tenant / owner: dropped with 200.
- contact: ingested onto the per-vendor unified inbox; the drain task fires
  the vendor Conversation 10s later with all messages from the window
  coalesced.
- customer: IDs swapped for UUIDs, identity persisted, then ingested onto
  the per-customer unified inbox.

Importing `chatbot.channels.whatsapp` registers the channel as a side effect.
"""

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

import backend.chatbot.channels.whatsapp  # noqa: F401  triggers channel registration
from backend.chatbot import _redis_queue
from backend.chatbot.channels import registry
from backend.chatbot.channels.base import ChannelIdentity, MediaAttachment
from backend.chatbot.channels.whatsapp import NonMessageEvent, _whatsapp_bot
from backend.chatbot.channels.whatsapp_resolver import (
    resolve_inbound_sender,
    resolve_or_create_customer_by_phone,
)
from backend.chatbot.conversations import inbox
from backend.chatbot.conversations.inbox import PartyKey
from backend.chatbot.conversations.registry import (
    customer_conversation,
    vendor_conversation,
)
from backend.chatbot.utils import object_storage
from backend.db import channel_identities

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


_R2_MEDIA_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
}


async def _materialize_media(
    attachments: list[MediaAttachment],
    business_id: str,
    party_id: str,
) -> list[dict]:
    """Pull each attachment's bytes from Meta and rehost for the agent.

    Preferred path: upload to R2 (S3-compatible) and return a fetchable URL,
    so the renderer hands the agent an `ImageUrl` / `DocumentUrl`. Fallback
    path (R2 not configured, or upload failed): base64-inline the bytes for
    the renderer to wrap in `BinaryContent`. Skips audio/video and any
    attachment we fail to download.
    """
    out: list[dict] = []
    for att in attachments:
        if att.kind not in ("image", "document"):
            continue
        if not att.media_id:
            continue
        downloaded = await asyncio.to_thread(
            _whatsapp_bot.download_media, att.media_id
        )
        if downloaded is None:
            continue
        data, mime = downloaded

        url: str | None = None
        if object_storage.is_configured():
            ext = _R2_MEDIA_EXT.get(mime, "")
            key = f"inbound/whatsapp/{business_id}/{party_id}/{att.media_id}{ext}"
            url = await asyncio.to_thread(
                object_storage.upload_bytes, data, key, mime
            )

        entry: dict = {"kind": att.kind, "mime_type": mime}
        if url:
            entry["url"] = url
        else:
            # Inline fallback so dev and tests work without R2.
            entry["data"] = base64.b64encode(data).decode("ascii")
        out.append(entry)
    return out


def _wamid(msg) -> str | None:
    """Extract Meta's per-message id from the parsed inbound. None if missing."""
    try:
        return msg.raw.get("messages", [{}])[0].get("id")
    except (AttributeError, IndexError):
        return None


@router.get("/whatsapp")
def whatsapp_verify(request: Request) -> PlainTextResponse:
    body = _whatsapp_bot.verify_webhook(request)
    # Meta accepts the handshake by echoing `hub.challenge` verbatim. Any
    # other body means the token/mode didn't match — surface that as 403 so
    # bad probes don't appear successful in logs and dashboards.
    status = 200 if body == request.query_params.get("hub.challenge") else 403
    return PlainTextResponse(body, status_code=status)


_WAMID_DEDUP_TTL = 24 * 60 * 60


def _wamid_dedup_key(wamid: str) -> str:
    return f"webhook:whatsapp:wamid:{wamid}"


async def _process_inbound(msg) -> None:
    """Resolve sender, materialize media, and ingest. Runs after we ack 200."""
    phone_number_id = msg.identity.channel_business_id
    wa_id = msg.identity.channel_user_id
    sender = await resolve_inbound_sender(phone_number_id, wa_id)
    wamid = _wamid(msg)

    match sender.kind:
        case "unknown_tenant":
            logger.warning(
                "dropping inbound for unknown tenant phone_number_id=%s",
                phone_number_id,
            )
            return
        case "owner":
            logger.info(
                "ignoring owner self-message business=%s wa_id=%s",
                sender.business_id,
                wa_id,
            )
            return
        case "contact":
            biz = str(sender.business_id)
            cid = str(sender.contact_id)
            text = msg.text or ""
            media = await _materialize_media(msg.media, biz, cid)
            if not text and not media:
                logger.info(
                    "contact inbound has no usable content contact=%s name=%s",
                    sender.contact_id,
                    sender.contact_name,
                )
                return
            convo = vendor_conversation(biz, cid)
            inbox.ingest(
                PartyKey.vendor(biz, cid),
                inbox.make_user_message_item(
                    text=text, raw=msg.raw, dedup_id=wamid, media=media
                ),
                dedup_id=wamid,
                runner=convo.drain,
            )
        case "customer":
            customer_uuid = await resolve_or_create_customer_by_phone(wa_id)
            biz = str(sender.business_id)
            cust = str(customer_uuid)
            resolved_identity = ChannelIdentity(
                business_id=biz,
                customer_id=cust,
                channel="whatsapp",
                channel_user_id=wa_id,
                channel_business_id=phone_number_id,
                last_inbound_at=msg.identity.last_inbound_at,
            )
            await channel_identities.upsert_identity(
                resolved_identity.model_copy(
                    update={"last_inbound_at": datetime.now(timezone.utc)}
                )
            )
            media = await _materialize_media(msg.media, biz, cust)
            convo = customer_conversation(biz, cust)
            inbox.ingest(
                PartyKey.customer(biz, cust),
                inbox.make_user_message_item(
                    text=msg.text or "",
                    raw=msg.raw,
                    dedup_id=wamid,
                    media=media,
                ),
                dedup_id=wamid,
                runner=convo.drain,
            )


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request, background: BackgroundTasks
) -> JSONResponse:
    # Meta retries until it sees a 2xx within ~5s. Media download + R2 upload
    # easily blow past that, so we ack 200 *first* and process in the
    # background. wamid dedup is claimed before scheduling so that retries
    # racing the background task are short-circuited at the door.
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
        return JSONResponse({"ok": True, "ignored": "non_message_event"}, status_code=200)

    wamid = _wamid(msg)
    if wamid is not None:
        if not _redis_queue.set_if_absent(
            _wamid_dedup_key(wamid), "1", _WAMID_DEDUP_TTL
        ):
            logger.info("duplicate whatsapp webhook wamid=%s", wamid)
            return JSONResponse({"ok": True, "deduped": True}, status_code=200)

    background.add_task(_process_inbound, msg)
    return JSONResponse({"ok": True}, status_code=200)
