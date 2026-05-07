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

Per-contact mutex is held across both — so an opening run and an inbound
drain can't race on the same contact. The lock key matches the unified
vendor-inbox lock so dispatch and the conversation drain share it.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
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

from backend.chatbot import _redis_queue
from backend.chatbot.channels import registry
from backend.chatbot.channels.base import ChannelIdentity
from backend.chatbot.messaging import dispatcher as messaging_dispatcher
from backend.config import MODEL_NAME
from backend.db import chat_storage, contacts, db_utils, events, events_search, outbound_ledger
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
    # Customer this outbound thread is on behalf of. Populated by the vendor
    # conversation factory from the latest open task; passed in by dispatch
    # at opening time. None when the contact reaches out unprompted with no
    # open tasks — back-office tools that need a customer return a
    # `no_customer_context` error in that case.
    customer_id: UUID | None = None
    # Manifest visible at run start. Opening run: the freshly-inserted task
    # plus any others already running. Reply run: every running task for
    # this contact. Empty list = vendor-initiated message with no open
    # work — the agent runs in journal-and-reply mode.
    open_tasks: list[OutboundTaskSummary] = Field(default_factory=list)
    max_depth: int = 3
    current_depth: int = 0


class UpdateItem(BaseModel):
    """One task update in a batch share_update call."""

    task_key: str = Field(description="The task this update belongs to.")
    customer_context: str | None = Field(
        default=None,
        description=(
            "Customer-safe summary with concrete answers. Set whenever "
            "there's something to tell the customer; omit when nothing "
            "customer-facing comes out of this update."
        ),
    )
    system_context: str | None = Field(
        default=None,
        description=(
            "Internal back-office notes (DB updates, restocking, follow-ups). "
            "Triggers downstream system actions. Omit when no system-side "
            "action is needed."
        ),
    )


_INSTRUCTIONS = """\
You are reaching out to {contact_name} (role: {contact_role}) on behalf of
{business_name}. You are NOT {contact_name} — you are CONTACTING them.

YOUR INPUT EACH RUN
- The first run on a NEW thread is an OPENING dispatch from the store
  manager. Its text is internal instructions describing what we need to
  ask {contact_name} — write a single clear, polite outreach in your own
  voice. Don't echo internal phrasing. Don't call share_update on this
  run; you haven't heard back yet.
- Every later run is triggered by {contact_name}'s reply (possibly several
  messages they sent in quick succession, joined together). Read the task
  manifest below — it lists both tasks still awaiting an answer AND tasks
  you recently resolved (the partner may be amending or correcting one of
  those). Decide which (if any) their reply maps to.

TASK MANIFEST WITH {contact_name}
{open_tasks_block}

WHEN THE MANIFEST HAS TASKS
- Match the partner's reply to one or more tasks above. A single message
  can answer multiple tasks at once.
- Default to sharing the update. If the partner's reply gives a usable
  answer to the question we asked, call share_update immediately — don't
  demand a more precise wording, don't ask follow-up clarification just
  to cosmetically tighten the answer.
- share_update can be called MORE THAN ONCE on the same task. A vendor
  often replies in stages or corrects what they said earlier ("actually
  only 5 in stock, not 10", "delivery slipped to Friday"). Whenever new
  info arrives that the customer should know, call share_update again
  with the latest customer_context — the system records every update and
  forwards each one. Recently-resolved tasks remain in this manifest
  precisely so you can amend them.
- Only ask a follow-up when a missing field is genuinely needed to ACT
  on the customer's question.
- A vague non-answer (no commitment, no concrete information) is the one
  case where pushing for specifics is warranted — and only on the field
  that matters.
- If {contact_name} declines or cannot help, still call share_update with
  customer_context describing the outcome.
- If the manifest summary isn't enough to know what a task was about,
  call get_task_details(task_key) to see the full dispatch prompt.

WHEN THE MANIFEST IS EMPTY
- {contact_name} has reached out without a pending request from us. Be
  brief and helpful and reply naturally.

DISAMBIGUATING WHO A REPLY IS ABOUT
- A vendor often handles many of our customers. When their reply could
  belong to more than one customer — or when the manifest doesn't carry
  enough customer context (e.g. you need a name, an order detail, or
  any prior turn) — call find_customer_context with the most distinctive
  phrase from their message (an address, an order id, a product, a
  customer name they mentioned). It returns candidate customers grouped
  with their recent turns and open tasks.
- Pick the customer whose recent events match. If two are plausible,
  ask the vendor a tight clarifying question grounded in the retrieved
  context ("the order for 1 Justice Coker Estate, size 15 — yes?"),
  then act on their next reply.
- Once you've picked a customer, pass that customer_id to surface_to_customer
  when relaying news that isn't already covered by a share_update payload.

ON UPDATE — for each UpdateItem, fill at least one of customer_context
or system_context:
- customer_context: customer-safe summary with concrete answers. No
  hedging, no deferring. Restate the full latest state, don't write a
  diff — the customer sees each update on its own.
- system_context: internal notes for back-office actions. Omit if
  nothing system-side needs to happen.

BACK-OFFICE TOOLS
You also play the back-office store manager. After resolving a task — or
during a vendor conversation that warrants it — keep the business state
consistent:
- update_inventory(sku, delta): adjust stock by delta (positive or negative).
- update_price(sku, new_price): set a product's price.
- update_vendor_contact(vendor_id, fields): fix a vendor's name/phone/email.
- record_note(subject, content): journal a back-office event.
- list_contacts(role=None): read the address book; pick a contact_id before
  dispatch_outbound.
- dispatch_outbound(contact_id, prompt, summary=None, timeout_seconds=3600):
  cascade outreach — e.g. switch to a backup vendor mid-conversation. Depth-
  limited.
- escalate_to_operator(reason, options=None): hand off to a human when
  automation can't proceed.
- surface_to_customer(summary): tell the customer something that is NOT
  already covered by a resolved task's customer_context (avoid duplicates).
  Returns no_customer_context when no customer is bound to this thread.

Be decisive. Use these tools as part of the same run that resolves tasks;
don't wait for a separate trigger. Stop when the back-office is consistent.

VOICE
- You are {business_name}'s representative. Professional, concise,
  explicit about what you need. WhatsApp-style — short paragraphs, no
  markdown, no UUIDs, no internal jargon.

RESPONSE FORMAT
- Plain prose addressed to {contact_name}. The dispatcher attaches the
  reference tag for reply tracking — do not add one yourself.
"""


def _format_manifest(tasks: list[OutboundTaskSummary]) -> str:
    if not tasks:
        return "(none — they reached out unprompted, or every prior task is past the grace window)"
    lines = []
    for t in tasks:
        if t.state == "succeeded" and t.resolved_at is not None:
            status = f"already shared an update {t.resolved_at:%Y-%m-%d %H:%M} — amend if they're correcting"
        else:
            status = "awaiting their reply"
        lines.append(
            f"- task_key={t.task_key} | role={t.contact_role} | "
            f"dispatched={t.dispatched_at:%Y-%m-%d %H:%M} | "
            f"status: {status} | summary: {t.summary}"
        )
    return "\n".join(lines)


_hooks: Hooks[OutboundDeps] = Hooks()


def _content_hash(customer_context: str | None, system_context: str | None) -> str:
    """Stable fingerprint of one share_update payload.

    Used both as the (task_key, content_hash) UNIQUE key in
    outbound_task_updates and as the customer-inbox dedup_id, so an agent
    that emits the same content twice fans out exactly once.
    """
    payload = f"{customer_context or ''}\x1f{system_context or ''}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


@_hooks.on.after_tool_execute(tools=["share_update"])
async def _on_share_update(
    ctx: RunContext[OutboundDeps],
    /,
    *,
    call: ToolCallPart,
    tool_def: ToolDefinition,
    args: dict[str, Any],
    result: Any,
) -> Any:
    """Append each accepted update to the history table and push the
    customer-side system_event for any item with customer_context.

    The dedup_id is keyed on the content hash, so a second share_update
    with the same payload is suppressed at the customer inbox while a
    correction (different payload) flows through. The history-table insert
    is `ON CONFLICT DO NOTHING` on the same hash for the same reason.

    Each ingest is independent — a per-task error is logged and skipped so
    other tasks still wake their customer.
    """
    # Lazy imports — conversations.registry imports from this module.
    from backend.chatbot.conversations import inbox as conv_inbox
    from backend.chatbot.conversations.inbox import PartyKey
    from backend.chatbot.conversations.registry import customer_conversation

    accepted = result.get("accepted", []) if isinstance(result, dict) else []
    if not accepted:
        return result
    for entry in accepted:
        task_key = entry["task_key"]
        cust_ctx = entry.get("customer_context")
        sys_ctx = entry.get("system_context")
        content_hash = entry["content_hash"]
        try:
            inserted = await outbound_ledger.insert_task_update(
                task_key, cust_ctx, sys_ctx, content_hash
            )
            if not inserted:
                # Same payload already recorded — don't re-fan to customer.
                continue
            if not cust_ctx:
                continue
            task = await outbound_ledger.get_by_key(task_key)
            if task is None:
                continue
            biz = str(task.business_id)
            cust = str(task.customer_id)
            convo = customer_conversation(biz, cust)
            dedup = f"share:{task_key}:{content_hash}"
            conv_inbox.ingest(
                PartyKey.customer(biz, cust),
                conv_inbox.make_system_event_item(
                    summary=cust_ctx,
                    source="outbound_reply",
                    contact_name=task.contact_name,
                    contact_role=task.contact_role,
                    task_key=task.task_key,
                    dedup_id=dedup,
                ),
                dedup_id=dedup,
                runner=convo.drain,
            )
            try:
                await events.insert_event(
                    business_id=task.business_id,
                    actor="business",
                    direction="out",
                    thread_id=f"customer:{cust}",
                    content=cust_ctx,
                    customer_id=task.customer_id,
                    contact_id=task.contact_id,
                    task_key=task.task_key,
                )
                events_search.bump_tenant(task.business_id)
            except Exception:
                logger.exception(
                    "events log failed (share_update fanout) task=%s", task_key
                )
        except Exception:
            logger.exception("share_update hook ingest failed task=%s", task_key)
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
    )


@outbound_agent.tool
async def share_update(
    ctx: RunContext[OutboundDeps],
    items: list[UpdateItem],
) -> dict[str, list[Any]]:
    """Share one or more updates from the vendor with the customer / system.

    Call this any time the partner conveys information the customer should
    know — including corrections or amendments to something they said
    earlier. The same task_key may appear across multiple share_update
    calls within the manifest grace window; each new payload is recorded
    and forwarded once.

    Each item must have at least one of customer_context or system_context.
    Items targeting tasks in a non-amendable terminal state (failed,
    timed_out, cancelled, escalated) are reported under `skipped`.
    """
    if not items:
        return {"accepted": [], "skipped": []}
    accepted: list[dict[str, Any]] = []
    skipped: list[str] = []
    for item in items:
        if not (item.customer_context or item.system_context):
            skipped.append(item.task_key)
            continue
        ok = await outbound_ledger.mark_completed(
            item.task_key, item.customer_context, item.system_context
        )
        if not ok:
            skipped.append(item.task_key)
            continue
        accepted.append(
            {
                "task_key": item.task_key,
                "customer_context": item.customer_context,
                "system_context": item.system_context,
                "content_hash": _content_hash(
                    item.customer_context, item.system_context
                ),
            }
        )
    return {"accepted": accepted, "skipped": skipped}


@outbound_agent.tool
async def find_customer_context(
    ctx: RunContext[OutboundDeps], query: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Search the multiparty event ledger for customers matching `query`.

    Use this whenever the partner's reply could plausibly belong to more
    than one customer, or whenever an instruction says "this customer"
    without naming who. Returns up to `limit` candidate customers, each
    with their recent multiparty turns (vendor side + customer side) and
    any open outbound task summaries — the minimum useful set for picking
    or asking the partner to confirm.

    Results are clustered by customer_id; an entry with customer_id=None
    is unattributed traffic (e.g. a vendor's unprompted message that
    hasn't been tied to a customer yet) — read those as candidates to
    attribute by content.
    """
    clusters = await events_search.find_customer_clusters(
        ctx.deps.business_id, query, limit=limit
    )
    return [
        {
            "customer_id": str(c.customer_id) if c.customer_id else None,
            "customer_name": c.customer_name,
            "score": c.score,
            "recent_events": c.recent_events,
            "open_task_summaries": c.open_task_summaries,
        }
        for c in clusters
    ]


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


# ---------------------------------------------------------------------------
# Back-office tools — merged from the former coordinator agent.
# ---------------------------------------------------------------------------


@outbound_agent.tool
async def update_inventory(
    ctx: RunContext[OutboundDeps], sku: str, delta: int
) -> dict[str, Any]:
    """Adjust stock for `sku` by `delta`. Returns the new quantity on success."""
    products = await db_utils.get_products(
        business_id=str(ctx.deps.business_id), name=sku, limit=50
    )
    match = next((p for p in products if (p.get("sku") or "") == sku), None)
    if match is None:
        return {"ok": False, "reason": f"sku '{sku}' not found"}

    new_qty = int(match.get("stock_quantity") or 0) + int(delta)
    updated = await db_utils.update_product_stock(str(match["id"]), new_qty)
    if updated is None:
        return {"ok": False, "reason": "update_failed"}
    return {"ok": True, "sku": sku, "new_qty": int(updated["stock_quantity"])}


@outbound_agent.tool
async def update_price(
    ctx: RunContext[OutboundDeps], sku: str, new_price: Decimal
) -> dict[str, Any]:
    """Set the unit price for `sku`."""
    products = await db_utils.get_products(
        business_id=str(ctx.deps.business_id), name=sku, limit=50
    )
    match = next((p for p in products if (p.get("sku") or "") == sku), None)
    if match is None:
        return {"ok": False, "reason": f"sku '{sku}' not found"}

    updated = await db_utils.update_product_price(str(match["id"]), new_price)
    if updated is None:
        return {"ok": False, "reason": "update_failed"}
    return {"ok": True, "sku": sku, "new_price": str(updated["price"])}


@outbound_agent.tool
async def update_vendor_contact(
    ctx: RunContext[OutboundDeps], vendor_id: str, fields: dict[str, str]
) -> dict[str, Any]:
    """Update a vendor's contact record. Accepted keys: name, phone, email."""
    allowed = {"name", "phone", "email"}
    payload = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not payload:
        return {"ok": False, "reason": "no updatable fields"}
    updated = await db_utils.update_vendor(UUID(vendor_id), **payload)
    if not updated:
        return {"ok": False, "reason": "vendor not found"}
    return {"ok": True, "vendor_id": vendor_id, "updated_fields": list(payload)}


@outbound_agent.tool
async def record_note(
    ctx: RunContext[OutboundDeps], subject: str, content: str
) -> dict[str, Any]:
    """Append a back-office journal entry."""
    # TODO: replace with a `coordinator_notes` table when persistence is needed.
    logger.info(
        "outbound_note | business_id=%s customer_id=%s subject=%s content=%s",
        ctx.deps.business_id,
        ctx.deps.customer_id,
        subject,
        content,
    )
    return {"ok": True, "logged": True}


@outbound_agent.tool
async def list_contacts(
    ctx: RunContext[OutboundDeps], role: str | None = None
) -> list[dict[str, Any]]:
    """List this business's address book. Optionally filter by role."""
    rows = await contacts.list_by_business(ctx.deps.business_id, role=role)
    return [
        {"id": str(c.id), "name": c.name, "role": c.role, "notes": c.notes}
        for c in rows
    ]


@outbound_agent.tool
async def dispatch_outbound(
    ctx: RunContext[OutboundDeps],
    contact_id: UUID,
    prompt: str,
    summary: str | None = None,
    timeout_seconds: int = 3600,
) -> dict[str, Any] | str:
    """Open a new system-initiated outbound thread. Returns the new task_key.

    `summary` is a short ≤80-char headline shown in the contact agent's
    manifest. Returns `no_customer_context` when the current run has no
    customer bound — the agent should resolve a task first or escalate.
    """
    if ctx.deps.customer_id is None:
        return {
            "error": "no_customer_context",
            "detail": "this thread has no customer bound; cannot cascade outbound",
        }
    return await dispatch(
        business_id=ctx.deps.business_id,
        customer_id=ctx.deps.customer_id,
        contact_id=contact_id,
        initiated_by="system",
        dispatch_prompt=prompt,
        summary=summary,
        timeout_seconds=timeout_seconds,
        parent_depth=ctx.deps.current_depth,
    )


@outbound_agent.tool
async def escalate_to_operator(
    ctx: RunContext[OutboundDeps],
    reason: str,
    options: list[str] | None = None,
) -> dict[str, Any]:
    """Hand off to a human operator when automation cannot proceed."""
    # TODO: wire to operator dashboard / Slack / email alerting once it exists.
    logger.warning(
        "outbound_escalation | business_id=%s customer_id=%s reason=%s options=%s",
        ctx.deps.business_id,
        ctx.deps.customer_id,
        reason,
        options or [],
    )
    return {"escalated": True}


@outbound_agent.tool
async def surface_to_customer(
    ctx: RunContext[OutboundDeps],
    summary: str,
    customer_id: UUID | None = None,
) -> dict[str, Any]:
    """Push a system_event into the customer inbox for central_agent to phrase.

    Pass `customer_id` explicitly when the run isn't bound to a customer
    (vendor-initiated thread, or one vendor handling multiple customers).
    The agent typically gets this id from `find_customer_context`. When
    omitted, falls back to the run's bound `customer_id`; if neither is
    available, returns `no_customer_context` so the agent can search and
    retry.
    """
    target_customer_id = customer_id or ctx.deps.customer_id
    if target_customer_id is None:
        return {"ok": False, "reason": "no_customer_context"}
    # Lazy import — conversations.registry imports from this module.
    from backend.chatbot.conversations import inbox as conv_inbox
    from backend.chatbot.conversations.inbox import PartyKey
    from backend.chatbot.conversations.registry import customer_conversation

    biz = str(ctx.deps.business_id)
    cust = str(target_customer_id)
    convo = customer_conversation(biz, cust)
    dedup = f"surface:{uuid4().hex}"
    conv_inbox.ingest(
        PartyKey.customer(biz, cust),
        conv_inbox.make_system_event_item(
            summary=summary,
            source="outbound_surface",
            dedup_id=dedup,
        ),
        dedup_id=dedup,
        runner=convo.drain,
    )
    try:
        await events.insert_event(
            business_id=ctx.deps.business_id,
            actor="business",
            direction="out",
            thread_id=f"customer:{cust}",
            content=summary,
            customer_id=target_customer_id,
            contact_id=ctx.deps.contact_id,
        )
        events_search.bump_tenant(ctx.deps.business_id)
    except Exception:
        logger.exception("events log failed (surface_to_customer)")
    return {"ok": True}


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
        last_inbound_at=None,
        channel_business_id=sender_phone_id,
    )


async def _send_to_party(
    *,
    business_id: UUID,
    contact_id: UUID,
    text: str,
    task_key: str | None = None,
    customer_id: UUID | None = None,
) -> str | None:
    """Send `text` to the contact. Returns None on success, status on failure.

    `task_key` is appended as a [Ref:] tag by the dispatcher when set —
    used on opening runs so the partner can disambiguate which thread their
    reply is for. On reply runs we have no single task_key (the run could
    have closed several at once or none), so we omit the ref.

    On successful send the message is appended to the multiparty event
    ledger (`events`) so subsequent retrieval can find it. Logging failures
    are swallowed (best-effort): the agent already sent the message, the
    ledger is observability and will heal on the next dispatch.
    """
    party_identity = await _contact_identity(contact_id)
    if party_identity is None:
        return f"contact deleted — reply not delivered"
    try:
        channel = registry.get(party_identity.channel)
    except KeyError:
        return f"unknown channel {party_identity.channel}"
    with _maybe_span(
        "outbound._send_to_party",
        contact_id=str(contact_id),
        channel=party_identity.channel,
        sender=party_identity.channel_business_id or party_identity.business_id,
        recipient=party_identity.channel_user_id,
        task_key=task_key,
    ):
        try:
            if task_key is not None:
                await messaging_dispatcher.dispatch_to_party(
                    channel, party_identity, text, task_key=task_key
                )
            else:
                await channel.send(party_identity, text)
        except Exception as exc:
            logger.exception("send_to_party failed contact=%s", contact_id)
            return f"dispatch failed: {exc}"

    try:
        await events.insert_event(
            business_id=business_id,
            actor="business",
            direction="out",
            thread_id=f"contact:{contact_id}",
            content=text,
            customer_id=customer_id,
            contact_id=contact_id,
            task_key=task_key,
        )
        events_search.bump_tenant(business_id)
    except Exception:
        logger.exception("events log failed (vendor send) contact=%s", contact_id)
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
        lock_key = f"lock:inbox:vendor:{business_id}:{contact.id}"
        while not _redis_queue.acquire_lock(lock_key, owner, ttl_seconds=60):
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
                current_depth=next_depth,
                customer_id=customer_id,
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
                # Opening run shouldn't normally call share_update — but if
                # it does, the share_update hook already routed everything.
                # Still send the agent's text to the party so they get the
                # outreach.
                send_status = await _send_to_party(
                    business_id=business_id,
                    contact_id=contact.id,
                    text=result.output,
                    task_key=task_key,
                    customer_id=customer_id,
                )
                if send_status is not None:
                    logger.warning(
                        "outbound dispatch send failed task=%s status=%s",
                        task_key,
                        send_status,
                    )
        finally:
            _redis_queue.release_lock(lock_key, owner)

    asyncio.create_task(_run())
    return task_key


async def deliver_contact_reply(
    business_id: str | UUID,
    contact_id: str | UUID,
    messages: list[str],
) -> str | None:
    """Run the outbound agent against a contact's coalesced inbound reply.

    Called by the unified vendor inbox drain runner with the per-contact
    mutex already held. `messages` is the list of inbound texts that arrived
    in the debounce window, joined here into a single agent input.

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
    )

    joined = "\n".join(m.strip() for m in messages if m.strip())
    if not joined:
        return "empty inbound — nothing to run agent on"

    # Log each inbound message to the multiparty event ledger BEFORE the
    # agent runs, so search calls during the run see the new turn. customer_id
    # is unknown here — the agent's search resolves it during reasoning.
    for raw in messages:
        text = raw.strip()
        if not text:
            continue
        try:
            await events.insert_event(
                business_id=biz,
                actor="contact",
                direction="in",
                thread_id=f"contact:{cid}",
                content=text,
                contact_id=cid,
            )
        except Exception:
            logger.exception("events log failed (vendor inbound) contact=%s", cid)
    events_search.bump_tenant(biz)

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
        # share_update was called during the run, _on_share_update already
        # fanned out customer-side notifications — the partner just needs
        # the agent's natural reply (no canned ack, no [Ref:] tag since
        # this run might span multiple tasks or none).
        send_status = await _send_to_party(
            business_id=biz, contact_id=cid, text=result.output
        )
        if send_status is not None:
            logger.warning(
                "contact reply send failed contact=%s status=%s", cid, send_status
            )
            return send_status
    return None
