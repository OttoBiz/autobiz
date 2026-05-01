"""Outbound agent — one thread to one vendor/logistics party.

Resolution state lives in the `outbound_tasks` ledger, not on deps. The agent
calls `mark_completed(customer_context, system_context)` when it's done; the
after-tool hook fans out via the resolution router. The agent's run output is
plain text; the messaging dispatcher owns delivery and reply-tracking (see
`messaging/dispatcher.py` for the per-channel wrapping).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Literal
from uuid import UUID, uuid4

# Avoid logfire's "not configured" warning on import paths that don't run
# `backend.observability.setup()` (notably unit tests). Production entry
# points (main.py, cli/tui.py) call setup() and override this default.
os.environ.setdefault("LOGFIRE_IGNORE_NO_CONFIG", "1")

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext, ToolDefinition
from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import ToolCallPart

from backend.chatbot.channels import registry
from backend.chatbot.channels.base import ChannelIdentity
from backend.chatbot.messaging import dispatcher as messaging_dispatcher
from backend.config import MODEL_NAME
from backend.db import channel_identities, chat_storage, contacts, outbound_ledger

try:
    import logfire

    _LOGFIRE_AVAILABLE = True
except ImportError:
    _LOGFIRE_AVAILABLE = False


@contextmanager
def _maybe_span(name: str, **attrs: Any) -> Iterator[None]:
    if _LOGFIRE_AVAILABLE:
        with logfire.span(name, **attrs):
            yield
    else:
        yield


class OutboundCancelled(Exception):
    """Raised by the per-turn cancellation guard to abort an in-flight run."""

    def __init__(self, task_key: str) -> None:
        self.task_key = task_key
        super().__init__(f"outbound task {task_key} cancelled")


OUTBOUND_MAX_DEPTH = 3

# Sent to the party once the ticket resolves, so they aren't left wondering
# whether their reply landed. Canned on purpose — the model's post-resolution
# wrap-up could repeat customer-only details or go off-script.
_RESOLUTION_ACK_TEXT = "Thanks — that's everything we needed. We'll take it from here."


class OutboundDeps(BaseModel):
    task_key: str
    business_id: UUID
    customer_id: UUID
    contact_id: UUID
    contact_name: str
    contact_role: str
    initiated_by: Literal["customer", "system"]
    dispatch_prompt: str
    business_name: str | None = None
    max_depth: int = 3
    current_depth: int = 0


instructions = """
You are reaching out to {contact_name} on behalf of {business_name} about ONE
specific issue. You are NOT {contact_name} — you are CONTACTING them. This
ticket concerns customer {customer_id} (do not mention this id to {contact_name}).

CONVERSATION FLOW
- The first run is the OPENING message. Write a single clear, polite message
  DIRECTED AT {contact_name} that asks for EVERYTHING the customer needs in one go —
  don't leave out fields you'll have to come back for. For product/stock
  tickets that normally means: availability, unit price, minimum order /
  pack size, and expected lead time or restock date. For logistics tickets:
  pickup address, handoff window, cost, and tracking. Adapt to the task.
- Do NOT call mark_completed on the opening run — you have not heard back.
- Each later run is triggered by {contact_name}'s reply. Read what they said.

WHEN TO CLOSE THE TICKET — the bar is "the customer's actual question can
be answered with what {contact_name} just told us." DEFAULT TO CLOSING.
- If {contact_name}'s reply answers the customer's question, call mark_completed
  even if some fields you also asked about are missing. Examples:
    * Customer asked when X is back in stock; vendor said "Tuesday" or
      "in stock now". CLOSE — don't push for unit price or MOQ they
      didn't volunteer.
    * Customer asked the price; vendor said "₦5,000". CLOSE — don't
      insist on restock date you also asked about.
- ONLY ask a follow-up when a missing field is genuinely needed to ACT
  on the customer's question (e.g. customer wants to place an order and
  you still don't know the MOQ). Asking just to fill out the form is
  exactly the over-asking we want to avoid.
- "We'll see" / "soon" / "should be fine" / "we'll get back to you" — that
  IS a non-answer. Push for specifics on the field that matters.
- If {contact_name} declines or cannot help on the customer's question, still
  call mark_completed with that outcome.

ON CLOSE — fill at least one of:
- customer_context: customer-safe summary with the concrete answers
  ("In stock at ₦15,000/pair, 10-unit minimum, ships in 2 days"). No
  hedging, no "I'll let you know". Set this whenever there's something
  to tell the customer (including a graceful "vendor cannot help" line).
- system_context: internal notes / DB actions the customer shouldn't see
  (e.g., "restock SKU-123 by +50 units"). Omit if nothing system-side
  needs to happen.

VOICE
- You are {business_name}'s representative. Be professional, concise, and
  explicit about what you need.
- Never include UUIDs, internal ids, or system jargon in messages to {contact_name}.

RESPONSE FORMAT
- Plain prose addressed to {contact_name}. The dispatcher attaches the reference
  tag for reply tracking — do not add one yourself.
"""

_hooks: Hooks[OutboundDeps] = Hooks()


@_hooks.on.before_model_request
async def _cancellation_guard(
    ctx: RunContext[OutboundDeps],
    request_context: Any,
    /,
) -> Any:
    # Ledger is the single source of truth for task state. Checking here (vs.
    # per-tool-call) catches cancellations between turns without racing the
    # model call that is about to go out.
    state = await outbound_ledger.get_state(ctx.deps.task_key)
    if state == "cancelled":
        raise OutboundCancelled(ctx.deps.task_key)
    return request_context


@_hooks.on.after_tool_execute(tools=["mark_completed"])
async def _on_mark_completed(
    ctx: RunContext[OutboundDeps],
    /,
    *,
    call: ToolCallPart,
    tool_def: ToolDefinition,
    args: dict[str, Any],
    result: Any,
) -> Any:
    from backend.chatbot.routers.outbound_resolution import route

    await route(ctx.deps.task_key)
    return result


outbound_agent: Agent[OutboundDeps, str] = Agent(
    model=MODEL_NAME,
    deps_type=OutboundDeps,
    output_type=str,
    capabilities=[_hooks],
)


@outbound_agent.instructions
def _build_instructions(ctx: RunContext[OutboundDeps]) -> str:
    return instructions.format(
        business_name=ctx.deps.business_name or "the business",
        customer_id=ctx.deps.customer_id,
        contact_name=ctx.deps.contact_name,
    )


@outbound_agent.tool
async def mark_completed(
    ctx: RunContext[OutboundDeps],
    customer_context: str | None = None,
    system_context: str | None = None,
) -> dict[str, bool]:
    """Resolve this outbound task. At least one context must be non-empty.

    Do not call this until {contact_name} has given concrete, actionable answers to
    every field the customer's question implies. If anything is still missing
    or non-committal, ask a follow-up instead.

    - customer_context: customer-safe summary with the concrete answers.
      Omit if the outcome has no customer-facing component.
    - system_context: internal notes for DB updates, follow-ups, back-office
      actions. Omit if nothing system-side needs to happen.
    """
    if not (customer_context or system_context):
        raise ValueError(
            "mark_completed requires at least one of customer_context or system_context"
        )
    await outbound_ledger.mark_completed(
        ctx.deps.task_key, customer_context, system_context
    )
    return {"acknowledged": True}


async def _contact_identity(contact_id: UUID) -> ChannelIdentity | None:
    """Build a ChannelIdentity targeting a real contact's wa_id.

    Looks up the contact row to get the real channel_user_id (the partner's
    wa_id) AND the right channel_business_id (the tenant's Meta-assigned
    phone_number_id used as sender). Falls back to the tenant's default
    whatsapp_phone_number_id when the contact doesn't override it.

    Returns None if the contact has been deleted since dispatch — the caller
    surfaces that as a status string so the operator sees the dropped reply.
    """
    contact = await contacts.get_by_id(contact_id)
    if contact is None:
        return None

    sender_phone_id = contact.channel_business_id
    if sender_phone_id is None:
        # Default: use the tenant's primary WABA as sender. The contact row
        # is FK'd to businesses, so a single point lookup is enough.
        from backend.db.connection import get_db

        pool = await get_db()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT whatsapp_phone_number_id FROM businesses WHERE id = $1",
                contact.business_id,
            )
        sender_phone_id = row["whatsapp_phone_number_id"] if row else None

    return ChannelIdentity(
        business_id=str(contact.business_id),
        customer_id=str(contact.id),  # placeholder — outbound dispatch doesn't read this
        channel=contact.channel,
        channel_user_id=contact.channel_user_id,
        channel_business_id=sender_phone_id,
    )


async def _send_to_party(
    *,
    task_key: str,
    contact_id: UUID,
    text: str,
) -> str | None:
    """Forward `text` to the contact identified by `contact_id`.

    Returns None on success, a status string when transport is missing or
    dispatch raised.
    """
    party_identity = await _contact_identity(contact_id)
    if party_identity is None:
        return f"task {task_key[:8]}: contact deleted — reply not delivered"
    try:
        channel = registry.get(party_identity.channel)
    except KeyError:
        return f"task {task_key[:8]}: unknown channel {party_identity.channel}"
    try:
        await messaging_dispatcher.dispatch_to_party(
            channel,
            party_identity,
            text,
            task_key=task_key,
        )
    except Exception as exc:
        await outbound_ledger.mark_failed(task_key, system_context=str(exc))
        return f"dispatch failed for task {task_key[:8]}: {exc}"
    return None


async def dispatch(
    *,
    business_id: UUID,
    customer_id: UUID,
    contact_id: UUID,
    initiated_by: Literal["customer", "system"],
    dispatch_prompt: str,
    business_name: str | None = None,
    timeout_seconds: int = 3600,
    parent_depth: int = 0,
) -> str:
    # Reject *before* writing the ledger so a depth-exhausted chain leaves no row.
    next_depth = parent_depth + 1
    if next_depth > OUTBOUND_MAX_DEPTH:
        raise ValueError(f"max_depth {OUTBOUND_MAX_DEPTH} exceeded")

    # Resolve the contact up front so the ledger snapshot has real values
    # even if the contact is deleted later. Bail early on unknown contact
    # rather than create a ledger row that can never deliver.
    contact = await contacts.get_by_id(contact_id)
    if contact is None:
        raise ValueError(f"unknown contact_id {contact_id}")

    task_key = uuid4().hex
    timeout_at = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
    await outbound_ledger.insert_task(
        task_key=task_key,
        business_id=business_id,
        customer_id=customer_id,
        initiated_by=initiated_by,
        dispatch_prompt=dispatch_prompt,
        timeout_at=timeout_at,
        contact_id=contact.id,
        contact_name=contact.name,
        contact_role=contact.role,
    )
    deps = OutboundDeps(
        task_key=task_key,
        business_id=business_id,
        customer_id=customer_id,
        contact_id=contact.id,
        contact_name=contact.name,
        contact_role=contact.role,
        initiated_by=initiated_by,
        dispatch_prompt=dispatch_prompt,
        business_name=business_name,
        current_depth=next_depth,
    )

    async def _run() -> None:
        await outbound_ledger.mark_running(task_key)
        with _maybe_span(
            "outbound.dispatch._run",
            task_key=task_key,
            contact_id=str(contact.id),
            contact_role=contact.role,
            initiated_by=initiated_by,
        ):
            try:
                result = await outbound_agent.run(dispatch_prompt, deps=deps)
            except OutboundCancelled:
                return
            except Exception as exc:
                await outbound_ledger.mark_failed(task_key, system_context=str(exc))
                return

            await chat_storage.append_outbound_history(task_key, result.new_messages())

            # Opening run shouldn't call mark_completed — but if the model
            # ignores instructions and resolves on the first turn, the
            # router has already routed to the customer. Don't echo the
            # model's wrap-up text to the party.
            if await outbound_ledger.get_state(task_key) != "running":
                return

            await _send_to_party(
                task_key=task_key,
                contact_id=contact.id,
                text=result.output,
            )

    asyncio.create_task(_run())
    return task_key


async def deliver_party_reply(task_key: str, party_text: str) -> str | None:
    """Continue an open outbound thread with a new message from the vendor.

    Returns:
        None on success (the agent's reply was dispatched, OR the agent
        resolved the ticket so nothing further goes to the party).
        A short status string when the message can't be delivered (task
        unknown / already resolved / no transport). Callers — both the
        smoke TUI and the future Flow webhook — surface this string so
        the operator isn't left staring at a silent UI.
    """
    task = await outbound_ledger.get_by_key(task_key)
    if task is None:
        return f"task {task_key[:8]} not found"
    if task.state != "running":
        return (
            f"task {task_key[:8]} is {task.state}; the agent already closed "
            "this ticket and won't process new replies on it"
        )

    if task.contact_id is None:
        return (
            f"task {task_key[:8]}: contact deleted — cannot continue thread"
        )
    deps = OutboundDeps(
        task_key=task.task_key,
        business_id=task.business_id,
        customer_id=task.customer_id,
        contact_id=task.contact_id,
        contact_name=task.contact_name,
        contact_role=task.contact_role,
        initiated_by=task.initiated_by,
        dispatch_prompt=task.dispatch_prompt,
    )
    history = await chat_storage.load_outbound_history(task_key)

    with _maybe_span(
        "deliver_party_reply",
        task_key=task_key,
        contact_id=str(task.contact_id),
        contact_role=task.contact_role,
        history_len=len(history),
    ):
        try:
            result = await outbound_agent.run(
                party_text, deps=deps, message_history=history
            )
        except OutboundCancelled:
            return f"task {task_key[:8]} was cancelled mid-run"
        except Exception as exc:
            await outbound_ledger.mark_failed(task_key, system_context=str(exc))
            return f"outbound agent errored on task {task_key[:8]}: {exc}"

        await chat_storage.append_outbound_history(task_key, result.new_messages())

        # If the agent called mark_completed, `_on_mark_completed` already
        # routed customer_context to the customer side. The model's wrap-up
        # text isn't sent — instead the party gets a short canned ack so the
        # thread closes politely. Other terminal states (failed/cancelled)
        # don't get an ack: the party didn't successfully help, sending
        # "thanks!" would be odd.
        post_state = await outbound_ledger.get_state(task_key)
        if post_state == "succeeded":
            return await _send_to_party(
                task_key=task_key,
                contact_id=task.contact_id,
                text=_RESOLUTION_ACK_TEXT,
            )
        if post_state != "running":
            return None

        return await _send_to_party(
            task_key=task_key,
            contact_id=task.contact_id,
            text=result.output,
        )
