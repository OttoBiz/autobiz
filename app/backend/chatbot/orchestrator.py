"""Channel-agnostic orchestrator — the one queue that feeds central_agent.

Everything the customer needs to hear about flows through a single per-customer
inbox queue:

- Customer messages (inbound webhooks or the smoke TUI) land via `handle_inbound`.
- Outbound vendor/logistics replies land via `deliver_system_event` when the
  resolution router resolves a task with customer-facing context.
- Coordinator-driven notices land via `deliver_system_event` too (the
  coordinator calls `surface_to_customer`, which enqueues a `system_event`).

In every case we take the per-customer lock, enqueue the new item, peek the
queue, run central_agent, send the reply on the customer's most-recent
channel, append chat history, and drain — in that order. `_drain_and_reply`
is the shared core; `handle_inbound` and `deliver_system_event` only differ in
how they source the channel identity.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic_ai.usage import UsageLimits

from backend.chatbot import inbox
from backend.chatbot.agents.central import agent as central_agent
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
        await _drain_and_reply(
            business_id, customer_id, identity_hint=msg.identity
        )
    finally:
        inbox.release_lock(business_id, customer_id, owner=owner)


async def deliver_system_event(
    business_id: str, customer_id: str, item: dict
) -> None:
    """Enqueue a system_event and wake central_agent to drain.

    Called by the outbound resolution router (vendor/logistics reply).
    Contract matches `handle_inbound`: acquire lock, enqueue, drain, release.

    On lock contention the item is still enqueued. If an in-flight central
    turn has already passed its `peek()` the item will sit until the next
    user-triggered turn — no silent drop, but the customer only sees it once
    they talk to us again. That is acceptable because the customer is in the
    middle of a turn with us anyway.
    """
    owner = uuid4().hex
    if not inbox.acquire_lock(business_id, customer_id, owner=owner):
        inbox.enqueue(business_id, customer_id, item)
        logger.info(
            "deliver_system_event: lock contention; enqueued for next turn biz=%s cust=%s",
            business_id,
            customer_id,
        )
        return
    try:
        inbox.enqueue(business_id, customer_id, item)
        await _drain_and_reply(business_id, customer_id, identity_hint=None)
    finally:
        inbox.release_lock(business_id, customer_id, owner=owner)


async def wake_central(business_id: str, customer_id: str) -> None:
    """Drain whatever is already queued for this customer.

    Used when items have been enqueued out-of-band (e.g., coordinator's
    `surface_to_customer` tool enqueued while holding the inbox lock under a
    different `owner`, or `outbound_resolution.route` enqueued an outbound
    reply item directly). Acquires the lock, peeks the queue, runs central
    if there's anything to drain, releases.

    Safe to call with an empty queue — `_drain_and_reply` short-circuits.
    Lock contention is not an error: the concurrent holder will drain on its
    own `peek()`, so we just return.
    """
    owner = uuid4().hex
    if not inbox.acquire_lock(business_id, customer_id, owner=owner):
        logger.info(
            "wake_central: lock contention; concurrent holder will drain biz=%s cust=%s",
            business_id,
            customer_id,
        )
        return
    try:
        await _drain_and_reply(business_id, customer_id, identity_hint=None)
    finally:
        inbox.release_lock(business_id, customer_id, owner=owner)


async def _drain_and_reply(
    business_id: str,
    customer_id: str,
    *,
    identity_hint: ChannelIdentity | None,
) -> None:
    """Peek queue, run central, send reply, append history, drain.

    Caller must hold the per-customer inbox lock. `identity_hint` short-circuits
    the channel lookup when the trigger is an inbound message whose identity
    we already have. System-triggered calls pass None and we fall back to the
    most-recent channel on file.
    """
    items = inbox.peek(business_id, customer_id)
    if not items:
        return

    identity = identity_hint
    if identity is None:
        identity = await channel_identities.get_most_recent_identity(
            UUID(business_id), UUID(customer_id)
        )
        if identity is None:
            logger.warning(
                "no channel identity on file; leaving %d item(s) queued biz=%s cust=%s",
                len(items),
                business_id,
                customer_id,
            )
            return

    prompt = _build_prompt(items)
    deps = AgentDeps(
        customer_id=customer_id,
        business_id=business_id,
        state={},
        outbound=[],
    )
    message_history = await chat_storage.load_history(business_id, customer_id)
    result = await central_agent.run(
        prompt,
        deps=deps,
        message_history=message_history,
        usage_limits=_CENTRAL_USAGE_LIMITS,
    )

    channel = registry.get(identity.channel)
    await messaging_dispatcher.dispatch_to_customer(
        channel, identity, result.output
    )

    # Persist only on successful send. If dispatch fails the prior history
    # remains untouched and the inbox items stay for the next turn.
    await chat_storage.append_history(
        business_id, customer_id, result.new_messages()
    )

    # Destructive drain only after a successful send. Any exception above
    # leaves items in the inbox for the next turn (drain-and-fail atomicity).
    inbox.drain(business_id, customer_id)


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
