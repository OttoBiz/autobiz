"""Conversation — the parameterized drain pipeline.

One Conversation per party (customer or vendor) is what the inbox drain task
calls. It encapsulates: identity resolution → prompt build → agent.run →
send → history append. It does NOT manage the inbox or lock — those are the
inbox module's job.

The two factory functions in `registry.py` build customer and vendor
Conversations with the right parts wired up. Webhook handlers and the
resolve hook obtain a Conversation from the registry, then call
inbox.ingest(party, item, runner=conversation.drain).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from backend.chatbot.channels.base import ChannelIdentity
from backend.chatbot.conversations.inbox import PartyKey
from backend.db import events as events_db
from backend.db import events_search

logger = logging.getLogger(__name__)


def _actor_for(party: PartyKey) -> str:
    """The 'actor' label for the OTHER side of this conversation.

    Customer-side conversations: the inbound items came from the customer.
    Vendor-side conversations: the inbound items came from the contact.
    Outbound text is always actor='business' regardless of party kind.
    """
    return "customer" if party.kind == "customer" else "contact"


async def _log_inbound_items(party: PartyKey, items: list[dict]) -> None:
    """Append every inbound user_message in `items` to the events ledger.

    System events (system_event items) are NOT logged — those are internal
    fan-outs from share_update / surface_to_customer that already get
    logged at their own write site, and re-logging here would double-count.

    Best-effort: a logging failure must never break the agent run.
    """
    biz_uuid = UUID(party.business_id)
    actor = _actor_for(party)
    direction = "in"

    customer_id: UUID | None = None
    contact_id: UUID | None = None
    thread_id: str
    if party.kind == "customer":
        customer_id = UUID(party.party_id)
        thread_id = f"customer:{party.party_id}"
    else:
        contact_id = UUID(party.party_id)
        thread_id = f"contact:{party.party_id}"

    bumped = False
    for it in items:
        if it.get("type") != "user_message":
            continue
        text = (it.get("payload", {}).get("text") or "").strip()
        if not text:
            continue
        try:
            await events_db.insert_event(
                business_id=biz_uuid,
                actor=actor,  # type: ignore[arg-type]
                direction=direction,
                thread_id=thread_id,
                content=text,
                customer_id=customer_id,
                contact_id=contact_id,
            )
            bumped = True
        except Exception:
            logger.exception(
                "events log failed (inbound) party=%s/%s",
                party.kind,
                party.party_id,
            )
    if bumped:
        events_search.bump_tenant(biz_uuid)


async def _log_outbound_reply(party: PartyKey, text: str) -> None:
    """Append the agent's reply (going TO the party) to the events ledger.

    customer_id is unknown here for vendor-side replies — the agent resolves
    it via find_customer_context during reasoning, not at send time. That's
    fine: the search index ranks by content regardless.
    """
    text = (text or "").strip()
    if not text:
        return
    biz_uuid = UUID(party.business_id)
    customer_id: UUID | None = None
    contact_id: UUID | None = None
    if party.kind == "customer":
        customer_id = UUID(party.party_id)
        thread_id = f"customer:{party.party_id}"
    else:
        contact_id = UUID(party.party_id)
        thread_id = f"contact:{party.party_id}"
    try:
        await events_db.insert_event(
            business_id=biz_uuid,
            actor="business",
            direction="out",
            thread_id=thread_id,
            content=text,
            customer_id=customer_id,
            contact_id=contact_id,
        )
        events_search.bump_tenant(biz_uuid)
    except Exception:
        logger.exception(
            "events log failed (outbound reply) party=%s/%s",
            party.kind,
            party.party_id,
        )


@dataclass(frozen=True)
class Conversation:
    party: PartyKey
    agent: Agent
    # Async functions; signatures match the existing chat_storage helpers.
    load_history: Callable[[PartyKey], Awaitable[list]]
    append_history: Callable[[PartyKey, list], Awaitable[None]]
    # Resolver returns the ChannelIdentity to send the reply on, or None when
    # the party has no channel on file (rare for vendor; possible for customer
    # if a webhook never landed).
    resolve_identity: Callable[[PartyKey], Awaitable[ChannelIdentity | None]]
    # Build the system/user prompt from a list of inbox items. Returns either
    # a plain string or a list (mixed text + pydantic_ai UserContent like
    # ImageUrl/DocumentUrl) when inbound items carry media.
    render_prompt: Callable[[list[dict]], Any]
    # Build the agent's deps for this run. Async because vendor deps need DB
    # lookups (open-task ledger) and customer deps stay async for parity.
    build_deps: Callable[[PartyKey], Awaitable[Any]]
    # Send hook: takes the resolved identity and the agent's text, dispatches
    # via the channel layer. Centralized so customer and vendor variants can
    # add tags / formatting before send.
    send: Callable[[ChannelIdentity, str], Awaitable[None]]
    usage_limits: UsageLimits | None = None

    async def drain(self, party: PartyKey, items: list[dict]) -> None:
        """Run the agent against `items` and send the reply. Raises on transient
        failure so the inbox keeps the items queued for retry."""
        identity = await self.resolve_identity(party)
        if identity is None:
            logger.warning(
                "no identity on file; leaving %d items queued party=%s",
                len(items),
                party,
            )
            # Raise so the inbox treats this as a transient failure and does
            # not drain the items. They'll be picked up next time identity is
            # available.
            raise RuntimeError(f"no_identity_for_{party.kind}")

        # Log inbound user_messages to the multiparty events ledger BEFORE
        # the agent runs, so any find_customer_context call inside the run
        # sees this turn's text.
        await _log_inbound_items(party, items)

        prompt = self.render_prompt(items)
        history = await self.load_history(party)
        deps = await self.build_deps(party)

        kwargs: dict[str, Any] = {"deps": deps, "message_history": history}
        if self.usage_limits is not None:
            kwargs["usage_limits"] = self.usage_limits

        result = await self.agent.run(prompt, **kwargs)
        await self.send(identity, result.output)
        # Persist only on successful send. If send raised, history stays as-is
        # and the items are NOT drained (we re-raise above).
        await self.append_history(party, result.new_messages())
        # Log the outbound reply post-send so the ledger reflects what the
        # other party actually saw (failed sends don't pollute the index).
        await _log_outbound_reply(party, result.output)
