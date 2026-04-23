"""Channel-agnostic orchestrator — single entry point for inbound messages.

Per-channel webhooks call `handle_inbound(InboundMessage)`. The orchestrator
acquires the per-customer lock, enqueues the new message, builds a prompt
from queued user/system items, runs central_agent, sends the reply through
the originating channel, and only then drains the inbox (drain-and-fail
atomicity). The lock contention branch enqueues without running, so the
in-flight central run picks the message up on its next user-triggered turn.

Outbound ledger lookups (pending/resolved) are NOT pushed into the prompt —
central_agent pulls them via its `get_outbound_status` tool when relevant.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from pydantic_ai.usage import UsageLimits

from backend.chatbot import inbox
from backend.chatbot.agents.central import (
    agent as central_agent,
    clear_outbound_status_cache,
)
from backend.chatbot.agents.deps import AgentDeps
from backend.chatbot.channels import registry
from backend.chatbot.channels.base import ChannelIdentity, InboundMessage
from backend.chatbot.messaging import dispatcher as messaging_dispatcher
from backend.db import channel_identities, chat_storage

# Cap a single customer turn at 10 model requests. A normal turn is 1–3
# requests (initial response, optional subagent call + finalization). Anything
# higher means the agent is looping; failing fast surfaces the bug instead of
# burning tokens for minutes before pydantic_ai's default 50 limit fires.
_CENTRAL_USAGE_LIMITS = UsageLimits(request_limit=10)

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

        prompt = _build_prompt(items)
        deps = AgentDeps(
            customer_id=customer_id,
            business_id=business_id,
            state={},
            outbound=[],
        )
        message_history = await chat_storage.load_history(business_id, customer_id)
        # Clear the per-turn outbound-status cache so a fresh fetch is
        # allowed once per turn — see central.get_outbound_status.
        clear_outbound_status_cache(business_id, customer_id)
        result = await central_agent.run(
            prompt,
            deps=deps,
            message_history=message_history,
            usage_limits=_CENTRAL_USAGE_LIMITS,
        )

        channel = registry.get(msg.identity.channel)
        await messaging_dispatcher.dispatch_to_customer(
            channel, msg.identity, result.output
        )

        # Persist only on successful send. If dispatch fails the prior history
        # remains untouched and the inbox items stay for the next turn.
        await chat_storage.append_history(
            business_id, customer_id, result.new_messages()
        )

        # Destructive drain only after a successful send. Any exception above
        # leaves items in the inbox for the next turn (drain-and-fail atomicity).
        inbox.drain(business_id, customer_id)
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


def _build_prompt(items: list[dict]) -> str:
    parts: list[str] = ["Customer messages this turn:"]
    for it in items:
        if it.get("type") == "user_message":
            text = it.get("payload", {}).get("text") or ""
            parts.append(f"- {text}")
        elif it.get("type") == "system_event":
            summary = it.get("payload", {}).get("summary") or ""
            parts.append(f"- (system) {summary}")
    return "\n".join(parts)
