"""Outbound resolution router — fan-out from a completed outbound task.

Called from the outbound agent's `after_tool_execute(mark_completed)` hook.
Translates a resolved ledger row into queued inbox items:

- `customer_context` → enqueued as a `system_event` and central_agent is
  woken up to phrase and send it (single delivery path — no direct push).
- `system_context` → runs the coordinator, which can update back-office
  state and (optionally) surface its own `system_event` to the customer.

Everything that ends up facing the customer goes through the same per-customer
queue that customer inbound messages go through, so the customer never sees
the same outcome twice.
"""

from datetime import datetime, timezone

from backend.chatbot import inbox, orchestrator
from backend.db import outbound_ledger
from backend.db.outbound_ledger import OutboundTaskRow
from backend.logging_config import get_logger

logger = get_logger(__name__)


async def route(task_key: str) -> None:
    task = await outbound_ledger.get_by_key(task_key)
    if task is None or task.state not in ("succeeded", "failed"):
        return

    # Run the coordinator first so any `surface_to_customer` events it emits
    # land in the inbox BEFORE central drains — the customer sees one coherent
    # turn that covers both the vendor's direct reply and any back-office
    # follow-ups.
    if task.system_context:
        await _run_coordinator(task)

    if task.customer_context:
        item = _outbound_reply_item(task)
        await orchestrator.deliver_system_event(
            str(task.business_id), str(task.customer_id), item
        )


def _outbound_reply_item(task: OutboundTaskRow) -> dict:
    return {
        "type": "system_event",
        "payload": {
            "summary": task.customer_context or "",
            "source": "outbound_reply",
            "party": task.party,
            "task_key": task.task_key,
        },
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
    }


async def _run_coordinator(task: OutboundTaskRow) -> None:
    # Coordinator needs the per-customer lock because it reads/writes shared
    # state (inbox via surface_to_customer, DB via its back-office tools).
    # We take the lock here and release it before the customer_context branch
    # runs — `deliver_system_event` takes the lock fresh for the drain.
    import uuid

    owner = uuid.uuid4().hex
    if not inbox.acquire_lock(
        str(task.business_id), str(task.customer_id), owner=owner
    ):
        logger.info("coordinator lock contention; dropping task=%s", task.task_key)
        return
    try:
        try:
            from backend.chatbot.agents.coordinator import (
                CoordinatorDeps,
                coordinator_agent,
            )
        except ImportError:
            logger.warning(
                "coordinator not available yet; skipping system_context for task=%s",
                task.task_key,
            )
            return
        deps = CoordinatorDeps(
            business_id=task.business_id,
            customer_id=task.customer_id,
            triggering_task_key=task.task_key,
        )
        await coordinator_agent.run(_build_coordinator_prompt(task), deps=deps)
    finally:
        inbox.release_lock(
            str(task.business_id), str(task.customer_id), owner=owner
        )


def _build_coordinator_prompt(task: OutboundTaskRow) -> str:
    return (
        f"An outbound task to {task.party} just completed.\n"
        f"system_context: {task.system_context}\n"
        f"Use your tools to make any back-office updates and decide whether to surface anything to the customer."
    )
