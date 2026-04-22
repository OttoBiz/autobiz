"""Channel-agnostic orchestrator — single entry point for inbound messages.

Per-channel webhooks call `handle_inbound(InboundMessage)`. The orchestrator
acquires the per-customer lock, enqueues the new message, drains queue + reads
ledger, runs central_agent, sends the reply through the originating channel,
and only then drains the inbox (drain-and-fail atomicity). The lock contention
branch enqueues without running, so the in-flight central run picks the message
up on its next user-triggered turn.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.chatbot import inbox
from backend.chatbot.agents.central import agent as central_agent
from backend.chatbot.agents.deps import AgentDeps
from backend.chatbot.channels import registry
from backend.chatbot.channels.base import ChannelIdentity, InboundMessage
from backend.chatbot.messaging import dispatcher as messaging_dispatcher
from backend.db import channel_identities, outbound_ledger
from backend.db.outbound_ledger import OutboundTaskRow

logger = logging.getLogger(__name__)


async def handle_inbound(msg: InboundMessage) -> None:
    """Single inbound entry-point. Per-channel webhooks call this."""
    business_id = msg.identity.business_id
    customer_id = msg.identity.customer_id
    owner = uuid4().hex

    if not inbox.acquire_lock(business_id, customer_id, owner=owner):
        # Another central run holds the lock — drop the message into the
        # inbox so it is picked up on the next user-triggered turn. We do not
        # spin or retry; the in-flight run is already past its drain point.
        inbox.enqueue(business_id, customer_id, _user_message_item(msg))
        logger.info(
            "lock contention; enqueued without running biz=%s cust=%s",
            business_id,
            customer_id,
        )
        return

    try:
        await channel_identities.upsert_identity(_identity_with_now(msg.identity))
        inbox.enqueue(business_id, customer_id, _user_message_item(msg))

        # Peek (not drain) so a failure mid-turn leaves items in place.
        items = inbox.peek(business_id, customer_id)
        cursor = inbox.get_cursor(business_id, customer_id)
        pending = await outbound_ledger.get_pending_for_customer(
            business_id, customer_id
        )
        resolved = await outbound_ledger.get_resolved_since(
            business_id, customer_id, cursor
        )

        prompt = _build_prompt(items, pending, resolved)
        deps = AgentDeps(
            customer_id=customer_id,
            business_id=business_id,
            chat_history=None,
            state={},
            outbound=[],
        )
        result = await central_agent.run(prompt, deps=deps)

        channel = registry.get(msg.identity.channel)
        await messaging_dispatcher.dispatch(channel, msg.identity, result.output)

        # Destructive drain only after a successful send. Any exception above
        # leaves items in the inbox for the next turn (drain-and-fail atomicity).
        inbox.drain(business_id, customer_id)
        if resolved:
            new_cursor = max(r.resolved_at for r in resolved)
            inbox.set_cursor(business_id, customer_id, new_cursor)
    finally:
        inbox.release_lock(business_id, customer_id, owner=owner)


def _user_message_item(msg: InboundMessage) -> dict:
    return {
        "type": "user_message",
        "payload": msg.model_dump(mode="json"),
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
    }


def _identity_with_now(identity: ChannelIdentity) -> ChannelIdentity:
    return identity.model_copy(
        update={"last_inbound_at": datetime.now(timezone.utc)}
    )


def _build_prompt(
    items: list[dict],
    pending: list[OutboundTaskRow],
    resolved: list[OutboundTaskRow],
) -> str:
    parts: list[str] = []
    if pending:
        parts.append("Pending outbound tasks (still in progress):")
        for t in pending:
            parts.append(f"- {t.party}: {t.dispatch_prompt}")
    if resolved:
        parts.append(
            "Recently resolved outbound tasks (use these to inform your reply):"
        )
        for t in resolved:
            parts.append(f"- {t.party}: {t.customer_context}")
    parts.append("Customer messages this turn:")
    for it in items:
        if it.get("type") == "user_message":
            text = it.get("payload", {}).get("text") or ""
            parts.append(f"- {text}")
        elif it.get("type") == "system_event":
            summary = it.get("payload", {}).get("summary") or ""
            parts.append(f"- (system) {summary}")
    return "\n".join(parts)
