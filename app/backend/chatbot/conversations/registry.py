"""Conversation factories — customer and vendor.

Customer: central_agent + customer history + most-recent channel identity +
inbox-style prompt renderer (mirrors today's orchestrator._build_prompt).

Vendor: outbound_agent + contact history + per-contact identity + plain-join
prompt renderer (mirrors today's outbound.deliver_contact_reply joined input).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic_ai import DocumentUrl, ImageUrl
from pydantic_ai.usage import UsageLimits

from backend.chatbot.agents.central import agent as central_agent
from backend.chatbot.agents.deps import AgentDeps
from backend.chatbot.agents.outbound import (
    OutboundDeps,
    _contact_identity,
    outbound_agent,
)
from backend.chatbot.channels import registry as channel_registry
from backend.chatbot.channels.base import ChannelIdentity
from backend.chatbot.conversations.conversation import Conversation
from backend.chatbot.conversations.inbox import PartyKey
from backend.chatbot.messaging import dispatcher as messaging_dispatcher
from backend.db import channel_identities, chat_storage, contacts, outbound_ledger

_CENTRAL_USAGE_LIMITS = UsageLimits(request_limit=10)


# --- Customer side -----------------------------------------------------------

async def _load_customer_history(party: PartyKey):
    return await chat_storage.load_history(party.business_id, party.party_id)


async def _append_customer_history(party: PartyKey, messages: list) -> None:
    await chat_storage.append_history(party.business_id, party.party_id, messages)


async def _resolve_customer_identity(party: PartyKey) -> ChannelIdentity | None:
    return await channel_identities.get_most_recent_identity(
        UUID(party.business_id), UUID(party.party_id)
    )


def _media_inputs(payload: dict) -> list[Any]:
    """Convert inbox media entries to pydantic_ai UserContent objects.

    Skips entries with no URL (the webhook couldn't resolve them) and
    audio/video kinds that the chat agents can't consume directly today.
    """
    out: list[Any] = []
    for m in payload.get("media") or []:
        url = m.get("url")
        if not url:
            continue
        kind = m.get("kind")
        if kind == "image":
            out.append(ImageUrl(url=url))
        elif kind == "document":
            out.append(DocumentUrl(url=url))
    return out


def _render_customer_prompt(items: list[dict]) -> Any:
    parts: list[str] = ["Customer messages this turn:"]
    media: list[Any] = []
    for it in items:
        if it.get("type") == "user_message":
            payload = it.get("payload", {})
            text = payload.get("text") or ""
            attachments = _media_inputs(payload)
            if attachments and not text:
                parts.append("- [attachment]")
            else:
                parts.append(f"- {text}")
            media.extend(attachments)
        elif it.get("type") == "system_event":
            summary = it.get("payload", {}).get("summary") or ""
            parts.append(f"- (system) {summary}")
    text_block = "\n".join(parts)
    if media:
        return [text_block, *media]
    return text_block


async def _build_customer_deps(party: PartyKey) -> AgentDeps:
    return AgentDeps(
        customer_id=UUID(party.party_id),
        business_id=UUID(party.business_id),
        state={},
        outbound=[],
    )


async def _send_customer(identity: ChannelIdentity, text: str) -> None:
    channel = channel_registry.get(identity.channel)
    await messaging_dispatcher.dispatch_to_customer(channel, identity, text)


def customer_conversation(business_id: str, customer_id: str) -> Conversation:
    return Conversation(
        party=PartyKey.customer(business_id, customer_id),
        agent=central_agent,
        load_history=_load_customer_history,
        append_history=_append_customer_history,
        resolve_identity=_resolve_customer_identity,
        render_prompt=_render_customer_prompt,
        build_deps=_build_customer_deps,
        send=_send_customer,
        usage_limits=_CENTRAL_USAGE_LIMITS,
    )


# --- Vendor side -------------------------------------------------------------

async def _load_vendor_history(party: PartyKey):
    return await chat_storage.load_contact_history(
        UUID(party.business_id), UUID(party.party_id)
    )


async def _append_vendor_history(party: PartyKey, messages: list) -> None:
    await chat_storage.append_contact_history(
        UUID(party.business_id), UUID(party.party_id), messages
    )


async def _resolve_vendor_identity(party: PartyKey) -> ChannelIdentity | None:
    return await _contact_identity(UUID(party.party_id))


def _render_vendor_prompt(items: list[dict]) -> Any:
    # Vendor inbox holds only user_message items today (vendor doesn't receive
    # system_events). Join texts in order, and forward any attachments inline
    # so the outbound agent can read receipts / shipping labels / photos a
    # vendor sends back.
    texts: list[str] = []
    media: list[Any] = []
    for it in items:
        if it.get("type") != "user_message":
            continue
        payload = it.get("payload", {})
        text = (payload.get("text") or "").strip()
        if text:
            texts.append(text)
        media.extend(_media_inputs(payload))
    text_block = "\n".join(texts)
    if media:
        return [text_block or "[attachment]", *media]
    return text_block


async def _build_vendor_deps(party: PartyKey) -> OutboundDeps:
    biz = UUID(party.business_id)
    cid = UUID(party.party_id)
    contact = await contacts.get_by_id(cid)
    if contact is None:
        raise ValueError(f"contact {cid} missing")
    open_tasks = await outbound_ledger.list_open_tasks_by_contact(biz, cid)
    customer_id_for_deps = open_tasks[0].customer_id if open_tasks else None
    return OutboundDeps(
        business_id=biz,
        contact_id=cid,
        contact_name=contact.name,
        contact_role=contact.role,
        open_tasks=open_tasks,
        customer_id=customer_id_for_deps,
    )


async def _send_vendor(identity: ChannelIdentity, text: str) -> None:
    # We bypass outbound._send_to_party because we already have the resolved
    # identity in hand; route directly through the channel.
    channel = channel_registry.get(identity.channel)
    await channel.send(identity, text)


def vendor_conversation(business_id: str, contact_id: str) -> Conversation:
    return Conversation(
        party=PartyKey.vendor(business_id, contact_id),
        agent=outbound_agent,
        load_history=_load_vendor_history,
        append_history=_append_vendor_history,
        resolve_identity=_resolve_vendor_identity,
        render_prompt=_render_vendor_prompt,
        build_deps=_build_vendor_deps,
        send=_send_vendor,
        usage_limits=None,
    )
