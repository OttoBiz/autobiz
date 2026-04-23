"""Outbound agent — one thread to one vendor/logistics party.

Resolution state lives in the `outbound_tasks` ledger, not on deps. The agent
calls `mark_completed(customer_context, system_context)` when it's done; the
after-tool hook fans out via the resolution router. The agent's run output is
a plain-text `Reply`; the messaging dispatcher owns delivery and reply-tracking
(see `messaging/dispatcher.py` for the per-channel wrapping).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext, ToolDefinition
from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import ToolCallPart

from backend.chatbot.channels import registry
from backend.chatbot.channels.base import ChannelIdentity
from backend.chatbot.messaging import dispatcher as messaging_dispatcher
from backend.chatbot.messaging.reply import Reply
from backend.config import MODEL_NAME
from backend.db import channel_identities, chat_storage, outbound_ledger


class OutboundCancelled(Exception):
    """Raised by the per-turn cancellation guard to abort an in-flight run."""

    def __init__(self, task_key: str) -> None:
        self.task_key = task_key
        super().__init__(f"outbound task {task_key} cancelled")


OUTBOUND_MAX_DEPTH = 3


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
You are an outbound agent for {business_name}. You handle exactly ONE issue per conversation.
This request concerns customer {customer_id}.

RULES:
- You are talking to {party} (a vendor/logistics partner), NOT the customer.
- Be professional and direct. State what you need clearly.
- When you have a definitive outcome, call `mark_completed` with:
    - `customer_context`: a customer-safe summary of what happened. Required if you need to relay anything to the customer.
    - `system_context`: internal-only notes — DB updates, follow-ups, vendor-facing details the customer shouldn't see.
  At least one of the two must be non-empty. A single reply can produce both.
- Do NOT end the conversation without calling `mark_completed`.
- If the party declines or cannot help, still call `mark_completed` describing the negative outcome.

RESPONSE FORMAT:
Reply with output structure only — plain prose to the party. Do not pick a UI surface;
the dispatcher handles delivery and reply-tracking so the party's reply routes
back to this ticket.
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


outbound_agent: Agent[OutboundDeps, Reply] = Agent(
    model=MODEL_NAME,
    deps_type=OutboundDeps,
    output_type=Reply,
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

    - customer_context: customer-safe summary. Omit if the outcome has no
      customer-facing component.
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

    # Resolve transport once at dispatch entry so the background agent run
    # never reaches back into the registry mid-flight. Both can be None
    # (system-initiated thread with no prior customer identity); _run handles
    # that by leaving the resolution in the ledger only.
    channel = await registry.get_for_customer(str(business_id), str(customer_id))
    customer_identity = await channel_identities.get_most_recent_identity(
        business_id, customer_id
    )

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
        try:
            result = await outbound_agent.run(dispatch_prompt, deps=deps)
        except OutboundCancelled:
            return
        except Exception as exc:
            await outbound_ledger.mark_failed(task_key, system_context=str(exc))
            return

        # Persist the opening exchange so the continuation helper has a real
        # message_history to thread back into the agent.
        await chat_storage.append_outbound_history(task_key, result.new_messages())

        if channel is None or customer_identity is None:
            # No transport for this thread; the ledger still carries the
            # resolution for the central agent to read on the next inbound.
            return

        try:
            await messaging_dispatcher.dispatch_to_party(
                channel,
                _vendor_identity(customer_identity, party),
                result.output,
                task_key=task_key,
            )
        except Exception as exc:
            await outbound_ledger.mark_failed(task_key, system_context=str(exc))

    asyncio.create_task(_run())
    return task_key


def _vendor_identity(customer_identity: ChannelIdentity, party: str) -> ChannelIdentity:
    """Re-target a customer identity at the vendor `party` address.

    `party` is the vendor's channel address — override channel_user_id so
    the message goes to the vendor, not the customer.
    """
    return ChannelIdentity(
        business_id=customer_identity.business_id,
        customer_id=customer_identity.customer_id,
        channel=customer_identity.channel,
        channel_user_id=party,
        last_inbound_at=customer_identity.last_inbound_at,
    )


async def deliver_party_reply(task_key: str, party_text: str) -> None:
    """Continue an open outbound thread with a new message from the vendor.

    The smoke harness calls this from the Vendor pane; the future Flow
    webhook will call it from `nfm_reply` payloads keyed by `flow_token =
    task_key`. Either way the path is the same:

    1. Look up the task; bail if it isn't running (already resolved/cancelled).
    2. Load prior message_history for this task.
    3. Re-enter outbound_agent with the vendor's text.
    4. Persist new messages and forward the agent's reply to the vendor.

    `mark_completed` may fire inside the run; the after-tool hook still
    routes the resolution as before.
    """
    task = await outbound_ledger.get_by_key(task_key)
    if task is None or task.state != "running":
        return

    deps = OutboundDeps(
        task_key=task.task_key,
        business_id=task.business_id,
        customer_id=task.customer_id,
        party=task.party,
        initiated_by=task.initiated_by,
        dispatch_prompt=task.dispatch_prompt,
    )

    history = await chat_storage.load_outbound_history(task_key)
    try:
        result = await outbound_agent.run(
            party_text, deps=deps, message_history=history
        )
    except OutboundCancelled:
        return
    except Exception as exc:
        await outbound_ledger.mark_failed(task_key, system_context=str(exc))
        return

    await chat_storage.append_outbound_history(task_key, result.new_messages())

    channel = await registry.get_for_customer(
        str(task.business_id), str(task.customer_id)
    )
    customer_identity = await channel_identities.get_most_recent_identity(
        task.business_id, task.customer_id
    )
    if channel is None or customer_identity is None:
        return

    try:
        await messaging_dispatcher.dispatch_to_party(
            channel,
            _vendor_identity(customer_identity, task.party),
            result.output,
            task_key=task_key,
        )
    except Exception as exc:
        await outbound_ledger.mark_failed(task_key, system_context=str(exc))
