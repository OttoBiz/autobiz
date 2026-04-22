"""Outbound agent — one thread to one vendor/logistics party.

Resolution state lives in the `outbound_tasks` ledger, not on deps. The agent
calls `mark_completed(customer_context, system_context)` when it's done; the
after-tool hook fans out via the resolution router.
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
from backend.chatbot.channels.base import Channel, ChannelIdentity
from backend.chatbot.channels.whatsapp_messages import (
    ButtonMessage,
    ListMessage,
    ListRow,
    ListSection,
    ReplyButton,
    Template,
    request_info,
)
from backend.config import MODEL_NAME
from backend.db import outbound_ledger


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

SEND TOOLS (pick the narrowest primitive that fits):
- `send_text_to_party(text)` — default. Free-form prose for open-ended questions or status updates.
- `send_buttons_to_party(body, buttons)` — yes/no or ≤3 quick-pick choices; faster reply than free text.
- `send_list_to_party(body, button_text, sections)` — pick-one from a longer enumerated set (e.g. SKUs, time slots).
- `request_structured_info(prompt, fields)` — collect typed fields via a WhatsApp Flow form (e.g. ETA, quantity, address).
- `send_template_to_party(template_name, vars)` — required to OPEN the conversation outside the WhatsApp 24h window; do not use inside the window.
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


async def _resolve_party_channel(
    deps: OutboundDeps,
) -> tuple[Channel, ChannelIdentity]:
    """Resolve the (channel, identity) pair for the outbound task's party.

    v1 assumption: `party` IS the vendor's WhatsApp phone number. The free-form
    send path in this agent has always treated it that way.

    TODO: lift `party` from `str` to a typed `Party(phone, name, channel)` once
    we support multi-channel vendors (Slack, email). At that point this resolver
    consults the party's preferred channel instead of hard-coding WhatsApp.
    """
    channel = registry.get("whatsapp")
    identity = ChannelIdentity(
        business_id=str(deps.business_id),
        # `customer_id` here marks the THREAD's owning customer for analytics /
        # window tracking; `channel_user_id` is the vendor phone we actually
        # send to. They are intentionally different identities.
        customer_id=str(deps.customer_id),
        channel="whatsapp",
        channel_user_id=deps.party,
        last_inbound_at=None,
    )
    return channel, identity


@outbound_agent.tool
async def send_text_to_party(ctx: RunContext[OutboundDeps], text: str) -> dict[str, Any]:
    """Send free-form text to the vendor/party. Default send primitive."""
    channel, identity = await _resolve_party_channel(ctx.deps)
    await channel.send(identity, text)
    return {"sent": True}


@outbound_agent.tool
async def send_buttons_to_party(
    ctx: RunContext[OutboundDeps],
    body: str,
    buttons: list[dict[str, str]],
) -> dict[str, Any]:
    """Send a body + up to 3 reply buttons. `buttons` = [{"id","title"}, ...]."""
    channel, identity = await _resolve_party_channel(ctx.deps)
    msg = ButtonMessage(
        body=body,
        buttons=[ReplyButton(id=b["id"], title=b["title"]) for b in buttons],
    )
    await channel.send_buttons(identity, msg)
    return {"sent": True, "buttons": [b["id"] for b in buttons]}


@outbound_agent.tool
async def send_list_to_party(
    ctx: RunContext[OutboundDeps],
    body: str,
    button_text: str,
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    """Send a list picker. `sections` = [{"title","rows":[{"id","title","description"?}]}]."""
    channel, identity = await _resolve_party_channel(ctx.deps)
    msg = ListMessage(
        body=body,
        button=button_text,
        sections=[
            ListSection(
                title=s["title"],
                rows=[
                    ListRow(
                        id=r["id"],
                        title=r["title"],
                        description=r.get("description"),
                    )
                    for r in s["rows"]
                ],
            )
            for s in sections
        ],
    )
    await channel.send_list(identity, msg)
    return {"sent": True}


@outbound_agent.tool
async def request_structured_info(
    ctx: RunContext[OutboundDeps],
    prompt: str,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    """Open the standing 'request information' Flow to collect typed fields.

    `fields` = [{"name","label","type"?}]. The labels render in the form;
    field names key the response payload.
    """
    channel, identity = await _resolve_party_channel(ctx.deps)
    flow = request_info(prompt, [f["label"] for f in fields])
    await channel.send_flow(identity, flow)
    return {"sent": True, "flow_id": flow.flow_id}


@outbound_agent.tool
async def send_template_to_party(
    ctx: RunContext[OutboundDeps],
    template_name: str,
    vars: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a pre-approved template — required to open the conversation outside the 24h window.

    `vars` is forwarded to `Channel.send_template` (e.g. {"language": "en",
    "components": [...]}) so language/parameter substitution stays the channel's
    concern, not the agent's.
    """
    channel, identity = await _resolve_party_channel(ctx.deps)
    template = Template(
        name=template_name,
        language=(vars or {}).get("language", "en"),
        components=(vars or {}).get("components", []),
    )
    await channel.send_template(identity, template, vars or {})
    return {"sent": True}


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
        try:
            await outbound_agent.run(dispatch_prompt, deps=deps)
        except OutboundCancelled:
            return
        except Exception as exc:
            await outbound_ledger.mark_failed(task_key, system_context=str(exc))

    asyncio.create_task(_run())
    return task_key
