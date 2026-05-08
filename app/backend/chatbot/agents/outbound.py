"""Outbound agent — one ongoing conversation per contact.

Contact-side counterpart to the customer-facing central agent. The unit of
conversation is a contact (a row in the address book), not a task. Tasks
(rows in `outbound_tasks`) are tags inside that conversation: the agent
sees a manifest of every OPEN task for the contact (`closed_at IS NULL`)
and decides which (if any) the partner's reply addresses.

Each task owns a markdown `log` column that the agent edits via:
  - `share_update` — append a "relayed to customer" section + fan out to
    the customer inbox. Does NOT close the task.
  - `update_task_log` — Hermes-style add/replace/remove for ad-hoc edits.
    No customer fan-out, no state change.
  - `close_task` — mark the task closed (stops appearing in the manifest).

Two entry points:
  - `dispatch(...)` — opens a new outbound thread on behalf of a customer.
  - `deliver_contact_reply(business_id, contact_id, messages)` — continues
    when the partner replies; runs the agent against the inbound text.

Per-contact mutex serializes both — an opening run and an inbound drain
can't race on the same contact.
"""

from __future__ import annotations

import asyncio
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
from backend.db import chat_storage, contacts, db_utils, outbound_ledger
from backend.db.outbound_ledger import (
    LogWriteError,
    OutboundTaskRow,
    OutboundTaskSummary,
)

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
    the inbound message addresses.
    """

    business_id: UUID
    contact_id: UUID
    contact_name: str
    contact_role: str
    business_name: str | None = None
    # Customer this outbound thread is on behalf of. Populated by the vendor
    # conversation factory from the latest open task; passed in by dispatch
    # at opening time. Often None when one vendor handles many customers —
    # the agent uses `find_tasks` to resolve which customer a given reply
    # belongs to, then passes the customer_id explicitly to surface_to_customer.
    customer_id: UUID | None = None
    # Manifest visible at run start: every OPEN task for this contact
    # (closed_at IS NULL). Empty list = vendor-initiated message with no
    # open work; agent runs in journal-and-reply mode.
    open_tasks: list[OutboundTaskSummary] = Field(default_factory=list)
    max_depth: int = 3
    current_depth: int = 0


# ---------------------------------------------------------------------------
# Tool input shapes
# ---------------------------------------------------------------------------


class UpdateItem(BaseModel):
    """One task update in a batch share_update call."""

    task_key: str = Field(description="The task this update belongs to.")
    relay_to_customer: str | None = Field(
        default=None,
        description=(
            "Customer-safe summary with concrete answers. Set whenever "
            "there's something to tell the customer; the system records "
            "it in the task log AND fans it out to the customer inbox. "
            "Omit when nothing customer-facing comes out of this update."
        ),
    )
    system_note: str | None = Field(
        default=None,
        description=(
            "Internal back-office note (DB updates, restocking, follow-ups). "
            "Recorded in the task log only — no customer fan-out. Omit "
            "when no system-side action is needed."
        ),
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_INSTRUCTIONS = """\
You are reaching out to {contact_name} (role: {contact_role}) on behalf of
{business_name}. You are NOT {contact_name} — you are CONTACTING them.

YOUR INPUT EACH RUN
- The first run on a NEW thread is an OPENING dispatch from the store
  manager. Its text is internal instructions describing what we need to
  ask {contact_name} — write a single clear, polite outreach in your own
  voice. Don't echo internal phrasing. Don't call share_update on this
  run; you haven't heard back yet.
- Every later run is triggered by {contact_name}'s reply (one or more
  messages joined together). Read the task manifest below — it lists
  every OPEN task with this contact, with a tail of each task's log so
  you have the recent narrative inline. Decide which (if any) tasks the
  reply addresses.

TASK MANIFEST WITH {contact_name}
{open_tasks_block}

WHEN THE MANIFEST HAS TASKS
- Match the partner's reply to one or more tasks above. A single message
  can answer multiple tasks at once.
- Default to relaying. If the partner's reply gives a usable answer to
  the question we asked, call share_update immediately — don't demand a
  more precise wording, don't ask follow-up clarification just to
  cosmetically tighten the answer.
- share_update appends a "## Relayed to customer" section to the task's
  log AND pushes a system_event to the customer's inbox. It does NOT
  close the task — vendor amendments later in the day will land on the
  same task and you'll call share_update again with the new info.
- A vague non-answer (no commitment, no concrete information) is the
  one case where pushing for specifics is warranted — and only on the
  field that matters.
- If {contact_name} declines or cannot help, still call share_update
  with relay_to_customer describing the outcome.
- The manifest carries log_excerpt (last ~400 chars). When you need the
  full log, call get_task_details(task_key).

WHEN THE MANIFEST IS EMPTY
- {contact_name} has reached out without a pending request from us. Be
  brief and helpful and reply naturally. If their message references a
  past order or interaction, call find_tasks with a distinctive phrase
  to find the closed task and act on it — typically by calling
  surface_to_customer to relay any new info.

DISAMBIGUATING WHO A REPLY IS ABOUT
- A vendor often handles multiple of our customers concurrently. When
  their reply could belong to more than one customer in the manifest:
  1. Call find_tasks(query=..., contact_id=<their id>) with the most
     distinctive phrase from their message (an address, an order id,
     a product, a customer name). It returns ranked task rows with
     full logs.
  2. Pick the task whose log matches. If two are plausible, ask the
     vendor a tight clarifying question grounded in the retrieved
     context ("the order for 1 Justice Coker Estate, size 15 — yes?")
     and stop. Their next reply disambiguates; you act then.
  3. Once you've picked, share_update on that task. surface_to_customer
     accepts an explicit customer_id from the find_tasks result for
     vendor-initiated relays that aren't covered by share_update.

CLOSING TASKS
- Call close_task(task_key, reason, final_log_entry?) when work is done
  (paid + delivered, vendor declined, customer cancelled, etc). Closed
  tasks drop from the manifest but stay searchable via find_tasks.
- The sweeper auto-closes tasks past their timeout. You don't need to
  watch the clock.

EDITING THE LOG WITHOUT FAN-OUT
- Use update_task_log for ad-hoc edits to a task's log that don't
  warrant a customer relay — fixing a typo in your own earlier section,
  appending an internal observation, compacting older sections when the
  log nears its size cap.
- Actions: add (append a new section), replace (substring replace; the
  old_text must be unique within the log), remove (substring delete).

BACK-OFFICE TOOLS
You also play the back-office store manager. After acting on a task — or
during a vendor conversation that warrants it — keep the business state
consistent:
- update_inventory(sku, delta): adjust stock by delta (positive or negative).
- update_price(sku, new_price): set a product's price.
- update_vendor_contact(vendor_id, fields): fix a vendor's name/phone/email.
- record_note(subject, content): journal a back-office event.
- list_contacts(role=None): read the address book; pick a contact_id before
  dispatch_outbound.
- dispatch_outbound(contact_id, prompt, timeout_seconds=3600): cascade
  outreach — e.g. switch to a backup vendor mid-conversation. Depth-
  limited.
- escalate_to_operator(reason, options=None): hand off to a human when
  automation can't proceed.
- surface_to_customer(summary, customer_id=None): tell the customer
  something not already covered by a share_update relay. Pass an explicit
  customer_id from find_tasks when the run isn't bound to a customer.

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
        return "(none — they reached out unprompted, or every prior task is closed)"
    lines = []
    for t in tasks:
        excerpt = t.log_excerpt.replace("\n", " ⏎ ")
        lines.append(
            f"- task_key={t.task_key} | role={t.contact_role} | "
            f"dispatched={t.dispatched_at:%Y-%m-%d %H:%M}\n"
            f"  log_excerpt: {excerpt}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Hooks — fire customer fan-out per accepted share_update item.
# ---------------------------------------------------------------------------


_hooks: Hooks[OutboundDeps] = Hooks()


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
    """Fan a system_event into the customer inbox for each accepted item
    that carried a relay_to_customer payload.

    The wrapper already appended the relay section to the task's log and
    enforced the not-recently-duplicated guard. Here we just push the
    customer-side event. Per-task errors are isolated so siblings still
    fan out.
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
        relay = entry.get("relay_to_customer")
        if not relay:
            continue
        try:
            task = await outbound_ledger.get_by_key(task_key)
            if task is None:
                continue
            biz = str(task.business_id)
            cust = str(task.customer_id)
            convo = customer_conversation(biz, cust)
            # Hash-keyed dedup at the inbox so identical content within the
            # TTL window can't double-fan-out (independent of the log dup
            # guard, which protects past TTL expiry).
            dedup = f"share:{task_key}:{entry['content_hash']}"
            conv_inbox.ingest(
                PartyKey.customer(biz, cust),
                conv_inbox.make_system_event_item(
                    summary=relay,
                    source="outbound_reply",
                    contact_name=task.contact_name,
                    contact_role=task.contact_role,
                    task_key=task.task_key,
                    dedup_id=dedup,
                ),
                dedup_id=dedup,
                runner=convo.drain,
            )
        except Exception:
            logger.exception("share_update hook ingest failed task=%s", task_key)
    return result


# ---------------------------------------------------------------------------
# Agent + tools
# ---------------------------------------------------------------------------


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


def _content_hash(text: str) -> str:
    """Short hash of a relay payload — used as the inbox dedup_id suffix.

    Borrowed from the previous design (no longer keyed in a sidecar table;
    just a stable id for inbox dedup within its TTL window).
    """
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _build_relay_section(item: UpdateItem) -> str:
    """Markdown section appended to the task's log for one share_update item."""
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = []
    if item.relay_to_customer:
        lines.append(f"## Relayed to customer {when}")
        lines.append(item.relay_to_customer)
    if item.system_note:
        if lines:
            lines.append("")
        lines.append(f"## System note {when}")
        lines.append(item.system_note)
    return "\n".join(lines)


@outbound_agent.tool
async def share_update(
    ctx: RunContext[OutboundDeps],
    items: list[UpdateItem],
) -> dict[str, list[Any]]:
    """Append a relay/note section to each task's log + fan out to the
    customer inbox for any item with relay_to_customer.

    Does NOT close the task. Vendor amendments later land on the same task
    via another share_update call. Items targeting closed tasks land in
    `skipped` with reason='task_closed'. Items whose payload duplicates
    the same task's recent log content are skipped with
    reason='duplicate_recent_relay'.
    """
    if not items:
        return {"accepted": [], "skipped": []}
    accepted: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for item in items:
        if not (item.relay_to_customer or item.system_note):
            skipped.append({"task_key": item.task_key, "reason": "empty_payload"})
            continue
        section = _build_relay_section(item)
        appended, skip_reason = await outbound_ledger.append_if_open_and_not_recent_dup(
            item.task_key, section
        )
        if not appended:
            skipped.append({"task_key": item.task_key, "reason": skip_reason or "skipped"})
            continue
        accepted.append(
            {
                "task_key": item.task_key,
                "relay_to_customer": item.relay_to_customer,
                "system_note": item.system_note,
                "content_hash": _content_hash(item.relay_to_customer or item.system_note or ""),
            }
        )
    return {"accepted": accepted, "skipped": skipped}


@outbound_agent.tool
async def update_task_log(
    ctx: RunContext[OutboundDeps],
    task_key: str,
    action: Literal["add", "replace", "remove"],
    content: str,
    old_text: str | None = None,
) -> dict[str, Any]:
    """Edit a task's log without firing a customer fan-out.

    - action='add': append `content` as a new markdown section.
    - action='replace': substitute exactly one occurrence of `old_text`
      with `content`. Errors when `old_text` is missing or ambiguous.
    - action='remove': delete exactly one occurrence of `old_text`
      (`content` must be empty or omitted).
    """
    try:
        if action == "add":
            new_log = await outbound_ledger.append_to_log(task_key, content)
        elif action == "replace":
            if old_text is None:
                return {"ok": False, "reason": "old_text_required"}
            new_log = await outbound_ledger.replace_in_log(
                task_key, old_text, content
            )
        elif action == "remove":
            target = old_text if old_text is not None else content
            new_log = await outbound_ledger.remove_from_log(task_key, target)
        else:
            return {"ok": False, "reason": f"unknown_action: {action}"}
    except LogWriteError as exc:
        return {"ok": False, "reason": str(exc)}
    return {"ok": True, "log": new_log, "log_bytes": len(new_log.encode("utf-8"))}


@outbound_agent.tool
async def close_task(
    ctx: RunContext[OutboundDeps],
    task_key: str,
    reason: str,
    final_log_entry: str | None = None,
) -> dict[str, Any]:
    """Mark a task closed. Drops it from the manifest; remains searchable.

    `reason` is a short label ("delivered", "vendor declined", "cancelled").
    `final_log_entry` is optional free-form markdown appended along with
    the closure marker.
    """
    closed = await outbound_ledger.close_task(
        task_key, reason=reason, final_log_entry=final_log_entry
    )
    if not closed:
        return {"ok": False, "reason": "already_closed_or_unknown"}
    return {"ok": True}


@outbound_agent.tool
async def find_tasks(
    ctx: RunContext[OutboundDeps],
    query: str,
    customer_id: UUID | None = None,
    contact_id: UUID | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """bm25 search across this tenant's tasks (open + closed within 180d).

    Use when:
    - a vendor's reply could belong to multiple customers and the manifest
      doesn't disambiguate
    - an instruction references past work that isn't in the manifest
      (closed tasks)
    - the agent needs to reference a prior task by content

    Filters: `customer_id` narrows to one customer's history, `contact_id`
    to one vendor's. Recency-decayed and score-floored — irrelevant or
    very old hits are dropped, not returned weakly.
    """
    rows = await outbound_ledger.find_tasks(
        ctx.deps.business_id,
        query,
        customer_id=customer_id,
        contact_id=contact_id,
        limit=limit,
    )
    return [_task_row_to_tool_dict(r) for r in rows]


def _task_row_to_tool_dict(row: OutboundTaskRow) -> dict[str, Any]:
    return {
        "task_key": row.task_key,
        "customer_id": str(row.customer_id),
        "contact_id": str(row.contact_id) if row.contact_id else None,
        "contact_name": row.contact_name,
        "contact_role": row.contact_role,
        "log": row.log,
        "dispatched_at": row.dispatched_at.isoformat(),
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
    }


@outbound_agent.tool
async def get_task_details(
    ctx: RunContext[OutboundDeps], task_key: str
) -> dict[str, Any] | None:
    """Fetch the full row + full log for a task in the manifest.

    Use when the manifest's log_excerpt isn't enough — e.g. you need the
    original dispatch brief or earlier sections that scrolled past the
    excerpt window.
    """
    task = await outbound_ledger.get_by_key(task_key)
    if task is None:
        return None
    return _task_row_to_tool_dict(task)


# ---------------------------------------------------------------------------
# Back-office tools — preserved as-is from prior design.
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
    timeout_seconds: int = 3600,
) -> dict[str, Any] | str:
    """Open a new system-initiated outbound thread. Returns the new task_key.

    Returns `no_customer_context` when the current run has no customer
    bound — the agent should resolve via find_tasks first.
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
    """Push a system_event into the customer inbox for the central agent
    to phrase.

    Pass `customer_id` explicitly when the run isn't bound to a customer
    (vendor-initiated thread, or one vendor handling multiple customers —
    typically derived from a find_tasks result). When omitted, falls back
    to the run's bound `customer_id`; if neither is available, returns
    `no_customer_context`.
    """
    target_customer_id = customer_id or ctx.deps.customer_id
    if target_customer_id is None:
        return {"ok": False, "reason": "no_customer_context"}
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
    return {"ok": True}


# ---------------------------------------------------------------------------
# Transport
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
    used on opening runs so the partner can disambiguate which thread
    their reply is for. On reply runs we have no single task_key (the
    run could have addressed several tasks or none), so we omit the ref.
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
    return None


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


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

    async def _run() -> None:
        owner = uuid4().hex
        # Block until we own the per-contact lock — an inbound drain may be
        # mid-flight and we can't run two agent calls on the same contact
        # concurrently. The lock has a 60s TTL so we won't deadlock.
        lock_key = f"lock:inbox:vendor:{business_id}:{contact.id}"
        while not _redis_queue.acquire_lock(lock_key, owner, ttl_seconds=60):
            await asyncio.sleep(0.5)
        try:
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
                    # Close the task with the error captured in the log.
                    await outbound_ledger.close_task(
                        task_key,
                        reason="dispatch_failed",
                        final_log_entry=f"Agent error: {exc}",
                    )
                    return
                await chat_storage.append_contact_history(
                    business_id, contact.id, result.new_messages()
                )
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

        send_status = await _send_to_party(
            business_id=biz, contact_id=cid, text=result.output
        )
        if send_status is not None:
            logger.warning(
                "contact reply send failed contact=%s status=%s", cid, send_status
            )
            return send_status
    return None
