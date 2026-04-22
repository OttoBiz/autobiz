"""Outbound resolution router — fan-out from a completed outbound task.

Called directly from the outbound agent's `after_tool_execute(mark_completed)`
hook. Reads the ledger row, pushes any `customer_context` through the channel
handler, and runs the coordinator (under the per-customer lock) when there is
`system_context` to act on.
"""

from uuid import uuid4

from backend.chatbot import inbox
from backend.chatbot.channels import registry
from backend.chatbot.channels.handler import handle_resolution
from backend.db import outbound_ledger
from backend.db.outbound_ledger import OutboundTaskRow
from backend.logging_config import get_logger

logger = get_logger(__name__)


async def route(task_key: str) -> None:
    """Fan out from a completed outbound task. Called by the outbound after_tool_execute hook."""
    task = await outbound_ledger.get_by_key(task_key)
    if task is None or task.state not in ("succeeded", "failed"):
        return

    if task.customer_context:
        channel = await registry.get_for_customer(
            str(task.business_id), str(task.customer_id)
        )
        if channel is not None:
            await handle_resolution(task, channel)
        else:
            logger.warning(
                "no channel for resolution task=%s biz=%s cust=%s",
                task_key,
                task.business_id,
                task.customer_id,
            )

    if task.system_context:
        await _run_coordinator(task)


async def _run_coordinator(task: OutboundTaskRow) -> None:
    owner = uuid4().hex
    if not inbox.acquire_lock(
        str(task.business_id), str(task.customer_id), owner=owner
    ):
        # Coordinator is reactive — drop on contention; the next central or
        # coordinator turn will re-read the ledger.
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
