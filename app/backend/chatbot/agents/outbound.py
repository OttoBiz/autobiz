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
from backend.db import channel_identities, chat_storage, outbound_ledger

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
    party: str
    initiated_by: Literal["customer", "system"]
    dispatch_prompt: str
    business_name: str | None = None
    max_depth: int = 3
    current_depth: int = 0


instructions = """
You are reaching out to {party} on behalf of {business_name} about ONE
specific issue. You are NOT {party} — you are CONTACTING them. This
ticket concerns customer {customer_id} (do not mention this id to {party}).

CONVERSATION FLOW
- The first run is the OPENING message. Write a single clear, polite message
  DIRECTED AT {party} that asks for EVERYTHING the customer needs in one go —
  don't leave out fields you'll have to come back for. For product/stock
  tickets that normally means: availability, unit price, minimum order /
  pack size, and expected lead time or restock date. For logistics tickets:
  pickup address, handoff window, cost, and tracking. Adapt to the task.
- Do NOT call mark_completed on the opening run — you have not heard back.
- Each later run is triggered by {party}'s reply. Read what they said.
- Before calling mark_completed, check every field the customer's question
  implies. If ANY required field is missing, ambiguous, or non-committal
  ("we'll see", "soon", "should be fine"), ASK A FOLLOW-UP — write another
  message addressed to {party} naming the exact fields you still need. A
  ticket can take several back-and-forths; that is expected.
- Only call mark_completed when {party} has given a definitive, actionable
  answer on every required field (or has clearly declined / cannot help).
  Then:
    - customer_context: customer-safe summary containing the concrete
      answers ("In stock at ₦15,000/pair, 10-unit minimum, ships in 2 days").
      No hedging, no "I'll let you know" — that is the agent's job to have
      already finished. Set this whenever there's something to tell the
      customer.
    - system_context: internal notes / DB actions the customer shouldn't
      see (e.g., "restock SKU-123 by +50 units", "vendor confirmed price
      change to ₦15,000"). Omit if nothing system-side needs to happen.
  At least one must be non-empty.
- If {party} clearly declines or cannot help, still call mark_completed
  with that outcome so the customer can be informed.

VOICE
- You are {business_name}'s representative. Be professional, concise, and
  explicit about what you need.
- Never include UUIDs, internal ids, or system jargon in messages to {party}.

RESPONSE FORMAT
- Plain prose addressed to {party}. The dispatcher attaches the reference
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
        party=ctx.deps.party,
    )


@outbound_agent.tool
async def mark_completed(
    ctx: RunContext[OutboundDeps],
    customer_context: str | None = None,
    system_context: str | None = None,
) -> dict[str, bool]:
    """Resolve this outbound task. At least one context must be non-empty.

    Do not call this until {party} has given concrete, actionable answers to
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


def _vendor_identity(customer_identity: ChannelIdentity, party: str) -> ChannelIdentity:
    """Re-target a customer identity at the vendor `party` address."""
    return ChannelIdentity(
        business_id=customer_identity.business_id,
        customer_id=customer_identity.customer_id,
        channel=customer_identity.channel,
        channel_user_id=party,
        last_inbound_at=customer_identity.last_inbound_at,
    )


async def _send_to_party(
    *,
    task_key: str,
    business_id: UUID,
    customer_id: UUID,
    party: str,
    text: str,
) -> str | None:
    """Resolve transport for this customer and forward `text` to `party`.

    Returns None on success, a status string when transport is missing or
    dispatch raised.
    """
    channel = await registry.get_for_customer(str(business_id), str(customer_id))
    customer_identity = await channel_identities.get_most_recent_identity(
        business_id, customer_id
    )
    if channel is None or customer_identity is None:
        return f"task {task_key[:8]}: no transport for party — reply not delivered"
    try:
        await messaging_dispatcher.dispatch_to_party(
            channel,
            _vendor_identity(customer_identity, party),
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
    party: str,
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

    task_key = uuid4().hex
    timeout_at = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
    await outbound_ledger.insert_task(
        task_key=task_key,
        business_id=business_id,
        customer_id=customer_id,
        party=party,
        initiated_by=initiated_by,
        dispatch_prompt=dispatch_prompt,
        timeout_at=timeout_at,
    )
    deps = OutboundDeps(
        task_key=task_key,
        business_id=business_id,
        customer_id=customer_id,
        party=party,
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
            party=party,
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
                business_id=business_id,
                customer_id=customer_id,
                party=party,
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

    deps = OutboundDeps(
        task_key=task.task_key,
        business_id=task.business_id,
        customer_id=task.customer_id,
        party=task.party,
        initiated_by=task.initiated_by,
        dispatch_prompt=task.dispatch_prompt,
    )
    history = await chat_storage.load_outbound_history(task_key)

    with _maybe_span(
        "deliver_party_reply",
        task_key=task_key,
        party=task.party,
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
                business_id=task.business_id,
                customer_id=task.customer_id,
                party=task.party,
                text=_RESOLUTION_ACK_TEXT,
            )
        if post_state != "running":
            return None

        return await _send_to_party(
            task_key=task_key,
            business_id=task.business_id,
            customer_id=task.customer_id,
            party=task.party,
            text=result.output,
        )
