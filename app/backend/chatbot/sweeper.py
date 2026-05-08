"""Outbound task timeout sweeper.

Periodically closes outbound tasks whose `timeout_at` has passed and
fires a customer-side `system_event` so the customer doesn't get
ghosted when a vendor never replies.
"""

import asyncio
import logging
from uuid import UUID, uuid4

from backend.db import outbound_ledger

logger = logging.getLogger(__name__)
SWEEP_INTERVAL_SECONDS = 60


async def _notify_customer_of_timeout(
    business_id: UUID,
    customer_id: UUID,
    contact_name: str,
    contact_role: str,
    task_key: str,
) -> None:
    """Push a system_event into the customer's inbox so the central agent
    explains the timeout in its next reply.

    Uses the same inbox primitive `surface_to_customer` uses; we don't
    need an agent run here — the customer's drain will pick it up.
    """
    # Lazy import — conversations.registry imports outbound_agent which
    # would cycle through this module.
    from backend.chatbot.conversations import inbox as conv_inbox
    from backend.chatbot.conversations.inbox import PartyKey
    from backend.chatbot.conversations.registry import customer_conversation

    biz = str(business_id)
    cust = str(customer_id)
    convo = customer_conversation(biz, cust)
    summary = (
        f"Heads up — we didn't hear back from {contact_name} ({contact_role}) "
        f"on a request that timed out. Looking into next steps."
    )
    dedup = f"timeout:{task_key}"
    conv_inbox.ingest(
        PartyKey.customer(biz, cust),
        conv_inbox.make_system_event_item(
            summary=summary,
            source="outbound_timeout",
            contact_name=contact_name,
            contact_role=contact_role,
            task_key=task_key,
            dedup_id=dedup,
        ),
        dedup_id=dedup,
        runner=convo.drain,
    )


async def sweep_once() -> list[dict]:
    """Close every open task past its timeout; notify each task's customer.

    Returns the list of closed task rows (dicts with task_key, business_id,
    customer_id, contact_id, contact_name) so callers / tests can inspect.
    """
    closed = await outbound_ledger.sweep_timeouts()
    for row in closed:
        try:
            await _notify_customer_of_timeout(
                business_id=row["business_id"],
                customer_id=row["customer_id"],
                contact_name=row["contact_name"],
                contact_role=row.get("contact_role", "partner"),
                task_key=row["task_key"],
            )
        except Exception:
            logger.exception(
                "timeout-customer-notify failed task=%s", row["task_key"]
            )
    return closed


async def sweep_loop(interval_seconds: int = SWEEP_INTERVAL_SECONDS) -> None:
    while True:
        try:
            await sweep_once()
        except Exception:
            logger.exception("sweeper iteration failed")
        await asyncio.sleep(interval_seconds)
