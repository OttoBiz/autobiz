"""Outbound agent — one ongoing conversation per contact.

This is the contact-side counterpart of the customer-facing central agent.
The unit of conversation is a contact (a row in the address book), not a
task. Tasks (rows in `outbound_tasks`) are tags inside that conversation:
the agent sees a manifest of every open task for the contact and can close
zero, one, or many of them in a single run depending on what the partner's
reply addresses.

Two entry points:

- `dispatch(...)`: opens a NEW outbound thread on behalf of a customer.
  Inserts the ledger row, runs the agent with the opening prompt, sends
  the outreach. Called by central / coordinator.
- `deliver_contact_reply(business_id, contact_id, messages)`: continues
  an existing thread when the partner replies. Loads the manifest + chat
  history, runs the agent once with the (debounced + coalesced) inbound
  text, sends the agent's reply.

Per-contact mutex (`contact_inbox.acquire_lock`) is held across both — so
an opening run and an inbound drain can't race on the same contact.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Literal
from uuid import UUID, uuid4

# Avoid logfire's "not configured" warning on import paths that don't run
# `backend.observability.setup()` (notably unit tests). Production entry
# points (main.py, cli/tui.py) call setup() and override this default.
os.environ.setdefault("LOGFIRE_IGNORE_NO_CONFIG", "1")

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext, ToolDefinition
from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import ToolCallPart

from backend.chatbot import contact_inbox
from backend.chatbot.channels import registry
from backend.chatbot.channels.base import ChannelIdentity
from backend.chatbot.messaging import dispatcher as messaging_dispatcher
from backend.config import MODEL_NAME
from backend.db import chat_storage, contacts, outbound_ledger
from backend.db.outbound_ledger import OutboundTaskSummary

logger = logging.getLogger(__name__)

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


OUTBOUND_MAX_DEPTH = 3


class OutboundDeps(BaseModel):
    """Runtime context for one outbound_agent run.

    Bound to a contact, NOT a task. The agent reads `open_tasks` to see
    what's currently in flight with this partner and decides which (if any)
    the inbound message resolves.
    """

    business_id: UUID
    contact_id: UUID
    contact_name: str
    contact_role: str
    business_name: str | None = None
    # Manifest visible at run start. Opening run: the freshly-inserted task
    # plus any others already running. Reply run: every running task for
    # this contact. Empty list = vendor-initiated message with no open
    # work — the agent runs in journal-and-reply mode.
    open_tasks: list[OutboundTaskSummary] = Field(default_factory=list)
    # Persistent agent-curated notes about this contact (Hermes-style
    # MEMORY.md). Loaded from contacts.agent_memory at run start; appended
    # to via the record_note tool.
    agent_memory: str | None = None
    max_depth: int = 3
    current_depth: int = 0


class ResolveItem(BaseModel):
    """One task close in a batch resolve_tasks call."""

    task_key: str = Field(description="The task to mark succeeded.")
    customer_context: str | None = Field(
        default=None,
        description=(
            "Customer-safe summary with concrete answers. Set whenever "
            "there's something to tell the customer; omit when nothing "
            "customer-facing comes out of this resolution."
        ),
    )
    system_context: str | None = Field(
        default=None,
        description=(
            "Internal back-office notes (DB updates, restocking, follow-ups). "
            "Triggers the coordinator agent. Omit when no system-side action "
            "is needed."
        ),
    )


_INSTRUCTIONS = """\
You are reaching out to {contact_name} (role: {contact_role}) on behalf of
{business_name}. You are NOT {contact_name} — you are CONTACTING them.

YOUR INPUT EACH RUN
- The first run on a NEW thread is an OPENING dispatch from the store
  manager. Its text is internal instructions describing what we need to
  ask {contact_name} — write a single clear, polite outreach in your own
  voice. Don't echo internal phrasing. Don't call resolve_tasks on this
  run; you haven't heard back yet.
- Every later run is triggered by {contact_name}'s reply (possibly several
  messages they sent in quick succession, joined together). Read the
  manifest of open tasks below, then decide which (if any) their reply
  resolves.

OPEN TASKS WITH {contact_name}
{open_tasks_block}

WHEN THERE ARE OPEN TASKS
- Match the partner's reply to one or more tasks above. A single message
  can answer multiple tasks (e.g. "yes, ankara at ₦15k, cotton at ₦8k"
  closes both).
- For each task the reply genuinely resolves, include it in
  resolve_tasks(items=[...]). DEFAULT TO CLOSING when the customer's
  question has a concrete answer — don't push for fields the partner
  didn't volunteer.
- ONLY ask a follow-up when a missing field is genuinely needed to ACT
  on the customer's question (e.g. they want to place an order and we
  still don't know the MOQ).
- "We'll see" / "soon" / "we'll get back to you" is a non-answer — push
  for specifics on the field that matters.
- If {contact_name} declines or cannot help, still close the task with
  customer_context describing the outcome.
- If the manifest summary isn't enough to know what a task was about,
  call get_task_details(task_key) to see the full dispatch prompt.

WHEN THERE ARE NO OPEN TASKS
- {contact_name} has reached out without a pending request from us. Be
  brief and helpful. If they shared something durable about their
  capabilities or constraints ("we don't carry red ankara anymore",
  "we're closed Mondays"), call record_note(text) to remember it for
  future runs. Then write a short polite reply.

ON CLOSE — for each ResolveItem, fill at least one of customer_context
or system_context:
- customer_context: customer-safe summary with concrete answers
  ("In stock at ₦15,000/pair, 10-unit minimum, ships in 2 days"). No
  hedging, no "I'll let you know".
- system_context: internal notes for back-office actions (e.g.,
  "restock SKU-123 by +50 units"). Omit if nothing system-side needs
  to happen.

VOICE
- You are {business_name}'s representative. Professional, concise,
  explicit about what you need. WhatsApp-style — short paragraphs, no
  markdown, no UUIDs, no internal jargon.

MEMORY ABOUT {contact_name}
{memory_block}

RESPONSE FORMAT
- Plain prose addressed to {contact_name}. The dispatcher attaches the
  reference tag for reply tracking — do not add one yourself.
"""


def _format_manifest(tasks: list[OutboundTaskSummary]) -> str:
    if not tasks:
        return "(none — they reached out unprompted, or every prior task is already closed)"
    lines = []
    for t in tasks:
        lines.append(
            f"- task_key={t.task_key} | role={t.contact_role} | "
            f"dispatched={t.dispatched_at:%Y-%m-%d %H:%M} | "
            f"summary: {t.summary}"
        )
    return "\n".join(lines)


def _format_memory(memory: str | None) -> str:
    if not memory:
        return "(no notes yet)"
    return memory.strip()


_hooks: Hooks[OutboundDeps] = Hooks()


@_hooks.on.after_tool_execute(tools=["resolve_tasks"])
async def _on_resolve_tasks(
    ctx: RunContext[OutboundDeps],
    /,
    *,
    call: ToolCallPart,
    tool_def: ToolDefinition,
    args: dict[str, Any],
    result: Any,
) -> Any:
    """Fan out outbound_resolution.route per closed task in parallel.

    The resolve_tasks tool already updated ledger state and returned the
    list of acknowledged task_keys; here we trigger the customer-side
    routing for each one concurrently — coordinator runs and customer
    inbox enqueues happen on independent customer locks so parallelism is
    safe.
    """
    from backend.chatbot.routers.outbound_resolution import route

    acknowledged = result.get("acknowledged", []) if isinstance(result, dict) else []
    if not acknowledged:
        return result
    await asyncio.gather(
        *(route(task_key) for task_key in acknowledged),
        return_exceptions=True,
    )
    return result


outbound_agent: Agent[OutboundDeps, str] = Agent(
    model=MODEL_NAME,
    deps_type=OutboundDeps,
    output_type=str,
    capabilities=[_hooks],
)


@outbound_agent.instructions
def _build_instructions(ctx: RunContext[OutboundDeps]) -> str:
    return _INSTRUCTIONS.format(
        business_name=ctx.deps.business_name or "the business",
        contact_name=ctx.deps.contact_name,
        contact_role=ctx.deps.contact_role,
        open_tasks_block=_format_manifest(ctx.deps.open_tasks),
        memory_block=_format_memory(ctx.deps.agent_memory),
    )


@outbound_agent.tool
async def resolve_tasks(
    ctx: RunContext[OutboundDeps],
    items: list[ResolveItem],
) -> dict[str, list[str]]:
    """Resolve one or more tasks at once.

    Pass an item per task the partner's reply genuinely resolves. Each item
    must have at least one of customer_context or system_context. Items
    that target tasks no longer in `running` state (already cancelled /
    timed out / closed elsewhere) are silently skipped — the ledger
    UPDATE only fires on running rows.
    """
    if not items:
        return {"acknowledged": [], "skipped": []}
    acknowledged: list[str] = []
    skipped: list[str] = []
    for item in items:
        if not (item.customer_context or item.system_context):
            skipped.append(item.task_key)
            continue
        ok = await outbound_ledger.mark_completed(
            item.task_key, item.customer_context, item.system_context
        )
        if ok:
            acknowledged.append(item.task_key)
        else:
            skipped.append(item.task_key)
    return {"acknowledged": acknowledged, "skipped": skipped}


@outbound_agent.tool
async def get_task_details(
    ctx: RunContext[OutboundDeps], task_key: str
) -> dict[str, Any] | None:
    """Fetch the full dispatch_prompt + state for a task in the manifest.

    Use when the manifest summary isn't enough to know what the task is
    about — e.g. the partner's reply is ambiguous and you need the
    original brief to disambiguate.
    """
    task = await outbound_ledger.get_by_key(task_key)
    if task is None:
        return None
    return {
        "task_key": task.task_key,
        "dispatch_prompt": task.dispatch_prompt,
        "summary": task.summary,
        "state": task.state,
        "dispatched_at": task.dispatched_at.isoformat(),
        "customer_context": task.customer_context,
    }


@outbound_agent.tool
async def record_note(
    ctx: RunContext[OutboundDeps], text: str
) -> dict[str, str]:
    """Append a durable note to your memory about this contact.

    For things worth remembering across future conversations: capabilities,
    constraints, preferences, recurring schedule. NOT for transient
    state — the manifest already shows open tasks, the chat history shows
    the conversation. Keep notes short and factual; older notes are
    trimmed when the journal fills up.
    """
    if not text.strip():
        return {"status": "skipped_empty"}
    journal = await contacts.append_agent_memory(ctx.deps.contact_id, text)
    return {"status": "recorded", "journal_chars": str(len(journal))}


# ---------------------------------------------------------------------------
# Transport — turn a contact_id into a real ChannelIdentity for sending.
# ---------------------------------------------------------------------------


async def _contact_identity(contact_id: UUID) -> ChannelIdentity | None:
    """Resolve a contact_id to a ChannelIdentity targeting their wa_id.

    `channel_user_id` is the partner's wa_id; `channel_business_id` is the
    tenant's Meta-assigned phone_number_id used as sender (per-contact
    override falling back to the tenant's primary WABA).
    """
    contact = await contacts.get_by_id(contact_id)
    if contact is None:
        return None

    sender_phone_id = contact.channel_business_id
    if sender_phone_id is None:
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
    *, contact_id: UUID, text: str, task_key: str | None = None
) -> str | None:
    """Send `text` to the contact. Returns None on success, status on failure.

    `task_key` is appended as a [Ref:] tag by the dispatcher when set —
    used on opening runs so the partner can disambiguate which thread their
    reply is for. On reply runs we have no single task_key (the run could
    have closed several at once or none), so we omit the ref.
    """
    party_identity = await _contact_identity(contact_id)
    if party_identity is None:
        return f"contact deleted — reply not delivered"
    try:
        channel = registry.get(party_identity.channel)
    except KeyError:
        return f"unknown channel {party_identity.channel}"
    try:
        if task_key is not None:
            await messaging_dispatcher.dispatch_to_party(
                channel, party_identity, text, task_key=task_key
            )
        else:
            await channel.send(party_identity, text)
    except Exception as exc:
        return f"dispatch failed: {exc}"
    return None


# ---------------------------------------------------------------------------
# Entry points: dispatch (opening run) + deliver_contact_reply (drain runner).
# ---------------------------------------------------------------------------


async def dispatch(
    *,
    business_id: UUID,
    customer_id: UUID,
    contact_id: UUID,
    initiated_by: Literal["customer", "system"],
    dispatch_prompt: str,
    summary: str | None = None,
    business_name: str | None = None,
    timeout_seconds: int = 3600,
    parent_depth: int = 0,
) -> str:
    """Open a new outbound thread. Returns the new task_key.

    Fire-and-forget: returns immediately after inserting the ledger row;
    the agent run + send happens in a background task under the per-contact
    mutex so no inbound drain can race the opening message.
    """
    next_depth = parent_depth + 1
    if next_depth > OUTBOUND_MAX_DEPTH:
        raise ValueError(f"max_depth {OUTBOUND_MAX_DEPTH} exceeded")

    contact = await contacts.get_by_id(contact_id)
    if contact is None:
        raise ValueError(f"unknown contact_id {contact_id}")

    task_key = uuid4().hex
    timeout_at = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
    # When the caller doesn't pass a summary, use the dispatch_prompt verbatim.
    # Manifest readability is the agent's job to optimize via the summary kwarg
    # — the harness shouldn't synthetically truncate.
    final_summary = (summary or "").strip() or dispatch_prompt
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
        summary=final_summary,
    )

    async def _run() -> None:
        owner = uuid4().hex
        # Block until we own the per-contact lock — an inbound drain may be
        # mid-flight and we can't run two agent calls on the same contact
        # concurrently. The lock has a 60s TTL so we won't deadlock.
        while not contact_inbox.acquire_lock(
            str(business_id), str(contact.id), owner
        ):
            await asyncio.sleep(0.5)
        try:
            await outbound_ledger.mark_running(task_key)
            open_tasks = await outbound_ledger.list_open_tasks_by_contact(
                business_id, contact.id
            )
            history = await chat_storage.load_contact_history(business_id, contact.id)
            deps = OutboundDeps(
                business_id=business_id,
                contact_id=contact.id,
                contact_name=contact.name,
                contact_role=contact.role,
                business_name=business_name,
                open_tasks=open_tasks,
                agent_memory=contact.agent_memory,
                current_depth=next_depth,
            )
            opening_input = (
                f"[NEW DISPATCH from store manager — task {task_key}]\n"
                f"{dispatch_prompt}"
            )
            with _maybe_span(
                "outbound.dispatch._run",
                task_key=task_key,
                contact_id=str(contact.id),
                contact_role=contact.role,
                initiated_by=initiated_by,
            ):
                try:
                    result = await outbound_agent.run(
                        opening_input, deps=deps, message_history=history
                    )
                except Exception as exc:
                    await outbound_ledger.mark_failed(task_key, system_context=str(exc))
                    return
                await chat_storage.append_contact_history(
                    business_id, contact.id, result.new_messages()
                )
                # Opening run shouldn't normally call resolve_tasks — but if
                # it does, the resolution router already routed everything.
                # Still send the agent's text to the party so they get the
                # outreach.
                send_status = await _send_to_party(
                    contact_id=contact.id, text=result.output, task_key=task_key
                )
                if send_status is not None:
                    logger.warning(
                        "outbound dispatch send failed task=%s status=%s",
                        task_key,
                        send_status,
                    )
        finally:
            contact_inbox.release_lock(str(business_id), str(contact.id), owner)

    asyncio.create_task(_run())
    return task_key


async def deliver_contact_reply(
    business_id: str | UUID,
    contact_id: str | UUID,
    messages: list[str],
) -> str | None:
    """Run the outbound agent against a contact's coalesced inbound reply.

    Called by the contact_inbox drain runner with the per-contact mutex
    already held. `messages` is the list of inbound texts that arrived in
    the debounce window, joined here into a single agent input.

    Returns None on success, a status string when delivery fails.
    """
    biz = UUID(str(business_id))
    cid = UUID(str(contact_id))

    contact = await contacts.get_by_id(cid)
    if contact is None:
        return f"contact {str(cid)[:8]} not found"
    if contact.business_id != biz:
        return f"contact {str(cid)[:8]} doesn't belong to business {str(biz)[:8]}"

    open_tasks = await outbound_ledger.list_open_tasks_by_contact(biz, cid)
    history = await chat_storage.load_contact_history(biz, cid)
    deps = OutboundDeps(
        business_id=biz,
        contact_id=cid,
        contact_name=contact.name,
        contact_role=contact.role,
        open_tasks=open_tasks,
        agent_memory=contact.agent_memory,
    )

    joined = "\n".join(m.strip() for m in messages if m.strip())
    if not joined:
        return "empty inbound — nothing to run agent on"

    with _maybe_span(
        "outbound.deliver_contact_reply",
        contact_id=str(cid),
        contact_role=contact.role,
        open_task_count=len(open_tasks),
        history_len=len(history),
    ):
        try:
            result = await outbound_agent.run(
                joined, deps=deps, message_history=history
            )
        except Exception as exc:
            logger.exception(
                "outbound agent errored on contact reply contact=%s", cid
            )
            return f"outbound agent errored: {exc}"

        await chat_storage.append_contact_history(biz, cid, result.new_messages())

        # The agent's plain-text output is the reply to the partner. If
        # resolve_tasks was called during the run, _on_resolve_tasks already
        # fanned out customer-side notifications — the partner just needs
        # the agent's natural reply (no canned ack, no [Ref:] tag since
        # this run might span multiple tasks or none).
        send_status = await _send_to_party(contact_id=cid, text=result.output)
        if send_status is not None:
            logger.warning(
                "contact reply send failed contact=%s status=%s", cid, send_status
            )
            return send_status
    return None
