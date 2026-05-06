"""Outbound task ledger accessors.

One row per outbound task. Append-only by identity — `state` mutates, rows
never delete. See `ARCHITECTURE_DECISIONS.md` → "Outbound task ledger".
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from backend.db.connection import get_db


class OutboundTaskRow(BaseModel):
    task_key: str
    business_id: UUID
    customer_id: UUID
    contact_id: UUID | None       # SET NULL on contact deletion preserves history rows
    contact_name: str             # snapshot at dispatch time
    contact_role: str             # snapshot at dispatch time
    initiated_by: Literal["customer", "system"]
    dispatch_prompt: str
    summary: str                  # one-line headline; what the agent sees in manifests
    state: Literal[
        "queued",
        "running",
        "succeeded",
        "failed",
        "timed_out",
        "cancelled",
        "escalated",
    ]
    customer_context: str | None
    system_context: str | None
    dispatched_at: datetime
    resolved_at: datetime | None
    timeout_at: datetime


class OutboundTaskSummary(BaseModel):
    """Manifest item — what the agent sees per open task without drilling in.

    Full dispatch_prompt is fetched on demand via get_task_details(task_key)
    when the vendor's reply is ambiguous and the agent needs more context.

    `state` and `resolved_at` are populated for both running and recently-
    resolved tasks: a task that succeeded within the grace window stays in
    the manifest so the agent can recognize a vendor's amendment / correction
    and call share_update again with the new info.
    """

    task_key: str
    contact_role: str
    summary: str
    dispatched_at: datetime
    customer_id: UUID  # so the agent knows which customer this is on behalf of
    state: Literal["running", "succeeded"] = "running"
    resolved_at: datetime | None = None


_COLUMNS = (
    "task_key, business_id, customer_id, contact_id, contact_name, contact_role, "
    "initiated_by, dispatch_prompt, summary, state, customer_context, system_context, "
    "dispatched_at, resolved_at, timeout_at"
)


async def insert_task(
    task_key: str,
    business_id: UUID,
    customer_id: UUID,
    initiated_by: str,
    dispatch_prompt: str,
    timeout_at: datetime,
    *,
    contact_id: UUID | None,
    contact_name: str,
    contact_role: str,
    summary: str,
) -> None:
    pool = await get_db()
    query = """
        INSERT INTO outbound_tasks (
            task_key, business_id, customer_id, contact_id, contact_name, contact_role,
            initiated_by, dispatch_prompt, summary, timeout_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
    """
    async with pool.acquire() as conn:
        await conn.execute(
            query,
            task_key,
            business_id,
            customer_id,
            contact_id,
            contact_name,
            contact_role,
            initiated_by,
            dispatch_prompt,
            summary,
            timeout_at,
        )


async def mark_running(task_key: str) -> bool:
    pool = await get_db()
    query = """
        UPDATE outbound_tasks
        SET state = 'running'
        WHERE task_key = $1 AND state = 'queued'
    """
    async with pool.acquire() as conn:
        status = await conn.execute(query, task_key)
    return _rowcount(status) > 0


async def mark_completed(
    task_key: str,
    customer_context: str | None,
    system_context: str | None,
) -> bool:
    """Resolve or amend a task. Allowed on running OR succeeded rows.

    Vendors often follow up with corrections after their first reply, so
    share_update may fire more than once per task. The first call flips
    running → succeeded; later calls refresh the latest customer_context /
    system_context on the row and bump resolved_at. A separate
    `outbound_task_updates` table preserves the trail.

    Terminal-but-not-succeeded states (failed, timed_out, cancelled,
    escalated) stay no-op so a stray late update doesn't reanimate them.
    """
    if not (customer_context or system_context):
        raise ValueError(
            "mark_completed requires at least one of customer_context or system_context"
        )

    pool = await get_db()
    query = """
        UPDATE outbound_tasks
        SET state = 'succeeded',
            customer_context = $2,
            system_context = $3,
            resolved_at = NOW()
        WHERE task_key = $1 AND state IN ('running', 'succeeded')
    """
    async with pool.acquire() as conn:
        status = await conn.execute(query, task_key, customer_context, system_context)
    return _rowcount(status) > 0


async def insert_task_update(
    task_key: str,
    customer_context: str | None,
    system_context: str | None,
    content_hash: str,
) -> bool:
    """Append one share_update entry to the task's update history.

    Returns False on UNIQUE (task_key, content_hash) conflict — i.e. the
    agent emitted the same content twice. Callers use that signal to skip
    the customer-side fan-out (no new info to relay).
    """
    pool = await get_db()
    query = """
        INSERT INTO outbound_task_updates (
            task_key, customer_context, system_context, content_hash
        )
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (task_key, content_hash) DO NOTHING
    """
    async with pool.acquire() as conn:
        status = await conn.execute(
            query, task_key, customer_context, system_context, content_hash
        )
    return _rowcount(status) > 0


async def mark_failed(task_key: str, system_context: str) -> bool:
    pool = await get_db()
    query = """
        UPDATE outbound_tasks
        SET state = 'failed',
            system_context = $2,
            resolved_at = NOW()
        WHERE task_key = $1 AND state = 'running'
    """
    async with pool.acquire() as conn:
        status = await conn.execute(query, task_key, system_context)
    return _rowcount(status) > 0


async def mark_cancelled(task_key: str) -> bool:
    pool = await get_db()
    query = """
        UPDATE outbound_tasks
        SET state = 'cancelled',
            resolved_at = NOW()
        WHERE task_key = $1 AND state IN ('queued', 'running')
    """
    async with pool.acquire() as conn:
        status = await conn.execute(query, task_key)
    return _rowcount(status) > 0


async def get_by_key(task_key: str) -> OutboundTaskRow | None:
    pool = await get_db()
    query = f"SELECT {_COLUMNS} FROM outbound_tasks WHERE task_key = $1"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, task_key)
    return OutboundTaskRow(**dict(row)) if row else None


RESOLVED_GRACE_MINUTES = 90


async def list_open_tasks_by_contact(
    business_id: UUID,
    contact_id: UUID,
) -> list[OutboundTaskSummary]:
    """Tasks the agent should still consider for this contact, newest first.

    Includes both running tasks AND tasks that succeeded within the last
    `RESOLVED_GRACE_MINUTES`. The grace window keeps recently-resolved tasks
    visible so the agent can recognize vendor amendments / corrections and
    call share_update again with the new info instead of dropping the
    update on the floor. Tasks past the grace window — or in any other
    terminal state — are excluded.

    Tenant-scoped (business_id) for defense-in-depth.
    """
    pool = await get_db()
    query = f"""
        SELECT task_key, contact_role, summary, dispatched_at, customer_id,
               state, resolved_at
        FROM outbound_tasks
        WHERE business_id = $1
          AND contact_id  = $2
          AND (
              state = 'running'
              OR (state = 'succeeded'
                  AND resolved_at > NOW() - INTERVAL '{RESOLVED_GRACE_MINUTES} minutes')
          )
        ORDER BY dispatched_at DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id, contact_id)
    return [OutboundTaskSummary(**dict(row)) for row in rows]


async def get_pending_for_customer(
    business_id: UUID, customer_id: UUID
) -> list[OutboundTaskRow]:
    pool = await get_db()
    query = f"""
        SELECT {_COLUMNS}
        FROM outbound_tasks
        WHERE business_id = $1
          AND customer_id = $2
          AND initiated_by = 'customer'
          AND state IN ('queued', 'running')
        ORDER BY dispatched_at
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id, customer_id)
    return [OutboundTaskRow(**dict(row)) for row in rows]


async def get_resolved_since(
    business_id: UUID, customer_id: UUID, cursor: datetime | None
) -> list[OutboundTaskRow]:
    pool = await get_db()
    query = f"""
        SELECT {_COLUMNS}
        FROM outbound_tasks
        WHERE business_id = $1
          AND customer_id = $2
          AND initiated_by = 'customer'
          AND customer_context IS NOT NULL
          AND resolved_at > COALESCE($3, '-infinity'::timestamptz)
        ORDER BY resolved_at
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id, customer_id, cursor)
    return [OutboundTaskRow(**dict(row)) for row in rows]


async def get_state(task_key: str) -> str | None:
    pool = await get_db()
    query = "SELECT state FROM outbound_tasks WHERE task_key = $1"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, task_key)
    return row["state"] if row else None


async def sweep_timeouts() -> list[str]:
    pool = await get_db()
    query = """
        UPDATE outbound_tasks
        SET state = 'timed_out',
            resolved_at = NOW()
        WHERE state IN ('queued', 'running')
          AND timeout_at < NOW()
        RETURNING task_key
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    return [row["task_key"] for row in rows]


def _rowcount(status: str) -> int:
    # asyncpg returns command tags like "UPDATE 1" / "UPDATE 0".
    return int(status.rsplit(" ", 1)[-1])
