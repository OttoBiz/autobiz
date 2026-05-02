"""Outbound resolution router — fan-out from a completed outbound task.

Called from the outbound agent's `after_tool_execute(mark_completed)` hook.
Translates a resolved ledger row into queued inbox items:

- `customer_context` → enqueued as a `system_event`.
- `system_context` → runs the coordinator, which can update back-office
  state and (optionally) surface its own `system_event` to the customer via
  its `surface_to_customer` tool.

Once everything is queued we call `orchestrator.wake_central` once so central
drains the combined queue in a single turn — the customer sees one coherent
message that covers both the vendor's direct answer and any coordinator
follow-ups. No direct `channel.send` push, no ledger poll from central.
"""

from datetime import datetime, timezone
from uuid import uuid4

import logfire

from backend.chatbot import inbox, orchestrator
from backend.db import outbound_ledger
from backend.db.outbound_ledger import OutboundTaskRow
from backend.logging_config import get_logger

logger = get_logger(__name__)


async def route(task_key: str) -> None:
    task = await outbound_ledger.get_by_key(task_key)
    if task is None or task.state not in ("succeeded", "failed"):
        logger.info(
            "route skipped task=%s (state=%s)",
            task_key,
            task.state if task else "missing",
        )
        return

    biz = str(task.business_id)
    cust = str(task.customer_id)
    has_customer = bool(task.customer_context)
    has_system = bool(task.system_context)

    with logfire.span(
        "outbound_resolution.route",
        task_key=task_key,
        business_id=biz,
        customer_id=cust,
        has_customer_context=has_customer,
        has_system_context=has_system,
        state=task.state,
    ):
        # Coordinator runs first under its own lock. Its failures (provider
        # errors, lock contention, bugs) must NOT block the customer-side
        # path — the ledger is already saved and the customer is owed their
        # reply regardless of back-office state.
        if has_system:
            try:
                await _run_coordinator(task)
            except Exception:
                logger.exception(
                    "coordinator failed for task=%s; continuing to customer wake",
                    task_key,
                )

        # Customer-side enqueue + wake. Wrapped independently so a wake_central
        # failure can't be confused with an enqueue failure. enqueue is
        # synchronous and writes to redis/local store; wake_central runs
        # central_agent under the per-customer lock.
        if has_customer:
            try:
                inbox.enqueue(biz, cust, _outbound_reply_item(task))
                logger.info(
                    "enqueued outbound_reply for customer task=%s biz=%s cust=%s",
                    task_key,
                    biz,
                    cust,
                )
            except Exception:
                logger.exception(
                    "inbox.enqueue failed for task=%s; central will not see this reply",
                    task_key,
                )
                return

        if has_customer or has_system:
            try:
                await orchestrator.wake_central(biz, cust)
            except Exception:
                logger.exception(
                    "wake_central failed for task=%s; queued items remain for next inbound",
                    task_key,
                )


def _outbound_reply_item(task: OutboundTaskRow) -> dict:
    return {
        "type": "system_event",
        "payload": {
            "summary": task.customer_context or "",
            "source": "outbound_reply",
            "contact_name": task.contact_name,
            "contact_role": task.contact_role,
            "task_key": task.task_key,
        },
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
    }


async def _run_coordinator(task: OutboundTaskRow) -> None:
    # Coordinator needs the per-customer lock because it reads/writes shared
    # state (inbox via surface_to_customer, DB via its back-office tools).
    # We release it before `route` calls wake_central — wake_central takes the
    # lock fresh for the drain.
    owner = uuid4().hex
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
    # Include customer_context so the coordinator knows what the customer is
    # already about to hear — it must NOT call surface_to_customer with a
    # near-duplicate of customer_context. Only surface when there is something
    # the customer_context does not already cover.
    parts = [f"An outbound task to {task.contact_name} ({task.contact_role}) just completed."]
    if task.customer_context:
        parts.append(
            f"customer_context (already queued for the customer): {task.customer_context}"
        )
    parts.append(f"system_context (for you to act on): {task.system_context}")
    parts.append(
        "Make any back-office updates you need. Only call surface_to_customer "
        "if there is something the customer still needs to know BEYOND what's "
        "already in customer_context — otherwise skip it to avoid duplicates."
    )
    return "\n".join(parts)
