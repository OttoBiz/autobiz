"""Coordinator agent — back-office store manager.

Reactive only. Triggered by `outbound:resolved` with non-empty `system_context`
(the resolution router invokes `coordinator_agent.run(...)` under the
per-customer lock). Never customer-facing directly; the only path back to the
customer is `surface_to_customer`, which enqueues a `system_event` for
central_agent to phrase.

No `chat_history` on deps — coordinator does not see customer conversation
history, only the ledger plus the new resolution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import Hooks

from backend.chatbot import inbox
from backend.chatbot.agents import outbound
from backend.config import MODEL_NAME
from backend.db import db_utils
from backend.logging_config import get_logger

logger = get_logger(__name__)


class CoordinatorDeps(BaseModel):
    business_id: UUID
    customer_id: UUID
    triggering_task_key: str
    max_depth: int = 3
    current_depth: int = 0


_INSTRUCTIONS = """\
You are the back-office store manager for this business.

Mental model: you are not on the sales floor. You don't talk to customers. You
read what just happened (a vendor or logistics partner replied, a system task
finished) and decide what the business needs to do about it — update inventory,
adjust prices, fix a vendor's contact info, jot a note in the journal, or kick
off another internal task.

You were invoked because an outbound task just resolved with a non-empty
`system_context`. That is the only reason you ever run.

Hard rules:
- You never speak to the customer directly. If the customer needs to know
  something, call `surface_to_customer(summary)` — central_agent will phrase it
  on the customer's next inbound message.
- You never see the customer's chat history. Don't reason about the
  conversation; reason about the back-office state.
- You see the full ledger (including system-initiated tasks). central_agent
  does not. Keep system-only details out of any `surface_to_customer` summary.

Tools available:
- `update_inventory(sku, delta)`: adjust stock by `delta` (positive or negative).
- `update_price(sku, new_price)`: set a product's price.
- `update_vendor_contact(vendor_id, fields)`: update vendor name/phone/email.
- `record_note(subject, content)`: append a back-office journal entry.
- `dispatch_outbound(party, prompt, timeout_seconds=3600)`: open a new
  system-initiated outbound thread (e.g., contact a backup vendor). Depth-limited.
- `surface_to_customer(summary)`: enqueue a system_event for central_agent.
- `escalate_to_operator(reason, options=None)`: hand off to a human when
  automation can't or shouldn't proceed.

Be decisive. One pass through the resolution. Stop when the back-office is
consistent with what was reported.
"""


hooks: Hooks[CoordinatorDeps] = Hooks()


coordinator_agent: Agent[CoordinatorDeps, str] = Agent(
    model=MODEL_NAME,
    deps_type=CoordinatorDeps,
    capabilities=[hooks],
)


@coordinator_agent.instructions
def _instructions(ctx: RunContext[CoordinatorDeps]) -> str:
    return _INSTRUCTIONS


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@coordinator_agent.tool
async def update_inventory(
    ctx: RunContext[CoordinatorDeps], sku: str, delta: int
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


@coordinator_agent.tool
async def update_price(
    ctx: RunContext[CoordinatorDeps], sku: str, new_price: Decimal
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


@coordinator_agent.tool
async def update_vendor_contact(
    ctx: RunContext[CoordinatorDeps], vendor_id: str, fields: dict[str, str]
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


@coordinator_agent.tool
async def record_note(
    ctx: RunContext[CoordinatorDeps], subject: str, content: str
) -> dict[str, Any]:
    """Append a back-office journal entry."""
    # TODO: replace with a `coordinator_notes` table when persistence is needed.
    # Logging suffices today: the resolution itself is in the ledger and the
    # note is auditable from the log stream.
    logger.info(
        "coordinator_note | business_id=%s customer_id=%s task=%s subject=%s content=%s",
        ctx.deps.business_id,
        ctx.deps.customer_id,
        ctx.deps.triggering_task_key,
        subject,
        content,
    )
    return {"ok": True, "logged": True}


@coordinator_agent.tool
async def dispatch_outbound(
    ctx: RunContext[CoordinatorDeps],
    party: str,
    prompt: str,
    timeout_seconds: int = 3600,
) -> str:
    """Open a new system-initiated outbound thread. Returns the new task_key."""
    return await outbound.dispatch(
        business_id=ctx.deps.business_id,
        customer_id=ctx.deps.customer_id,
        party=party,
        initiated_by="system",
        dispatch_prompt=prompt,
        timeout_seconds=timeout_seconds,
        parent_depth=ctx.deps.current_depth,
    )


@coordinator_agent.tool
async def surface_to_customer(
    ctx: RunContext[CoordinatorDeps], summary: str
) -> dict[str, Any]:
    """Push a system_event into the customer inbox for central_agent to phrase."""
    item = {
        "type": "system_event",
        "payload": {
            "summary": summary,
            "source_task": ctx.deps.triggering_task_key,
        },
        "enqueued_at": _now_iso(),
    }
    inbox.enqueue(str(ctx.deps.business_id), str(ctx.deps.customer_id), item)
    return {"ok": True}


@coordinator_agent.tool
async def escalate_to_operator(
    ctx: RunContext[CoordinatorDeps],
    reason: str,
    options: list[str] | None = None,
) -> dict[str, Any]:
    """Hand off to a human operator when automation cannot proceed."""
    # TODO: wire to operator dashboard / Slack / email alerting once it exists.
    logger.warning(
        "coordinator_escalation | business_id=%s customer_id=%s task=%s reason=%s options=%s",
        ctx.deps.business_id,
        ctx.deps.customer_id,
        ctx.deps.triggering_task_key,
        reason,
        options or [],
    )
    return {"escalated": True}
