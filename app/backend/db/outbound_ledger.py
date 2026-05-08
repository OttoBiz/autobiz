"""Outbound task ledger — one row per task, agent-curated markdown log.

Each row in `outbound_tasks` is a unit of customer-facing work crossing a
contact (vendor / partner / etc). The agent's narrative for the task lives
in the `log` column as markdown; mutation primitives are append/replace/
remove with a hard size cap (Hermes-style substring CRUD).

Open vs closed:
  - `closed_at IS NULL` is the only open-task signal.
  - `share_update` appends to log + fans out to customer; does NOT close.
  - Tasks close via `close_task` (agent), the timeout sweeper, or operators.

Search:
  - bm25 over `log` content per tenant; lazy in-process index, version
    counter in Redis so multi-worker deploys stay coherent.
  - Hard cutoff: closed tasks past `_FIND_TASKS_CUTOFF_DAYS` are dropped
    from the corpus; score floor drops trailing weak hits.

See ARCHITECTURE_DECISIONS.md → "Outbound task ledger".
"""

from __future__ import annotations

import logging
import math
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

import bm25s
from pydantic import BaseModel

from backend.db.cache_utils import redis_conn
from backend.db.connection import get_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Row shapes
# ---------------------------------------------------------------------------


class OutboundTaskRow(BaseModel):
    task_key: str
    business_id: UUID
    customer_id: UUID
    contact_id: UUID | None       # SET NULL on contact deletion preserves history
    contact_name: str             # snapshot at dispatch time
    contact_role: str             # snapshot at dispatch time
    initiated_by: Literal["customer", "system"]
    log: str                      # markdown narrative
    dispatched_at: datetime
    timeout_at: datetime
    closed_at: datetime | None    # NULL = open


class OutboundTaskSummary(BaseModel):
    """Manifest item — what the agent sees per open task without drilling in.

    `log_excerpt` is the tail of the log (last ~400 chars) so the agent has
    the most-recent narrative inline. Full log via get_by_key when needed.
    """

    task_key: str
    contact_role: str
    log_excerpt: str
    dispatched_at: datetime
    customer_id: UUID


_COLUMNS = (
    "task_key, business_id, customer_id, contact_id, contact_name, contact_role, "
    "initiated_by, log, dispatched_at, timeout_at, closed_at"
)


# ---------------------------------------------------------------------------
# Tuning constants — exposed so tests + ops can override.
# ---------------------------------------------------------------------------

LOG_HARD_CAP_BYTES = 8 * 1024            # ~8KB per task log
LOG_EXCERPT_TAIL_CHARS = 400             # manifest tail window
_BM25_INDEX_DOC_LIMIT = 5000
_RECENCY_HALFLIFE_DAYS = 14.0
_SCORE_FLOOR = 0.5                       # drop weak hits below this weighted score
_FIND_TASKS_CUTOFF_DAYS = 180            # closed tasks past this aren't indexed
_INJECTION_PATTERNS = [
    re.compile(r"ignore (?:all )?previous instructions", re.IGNORECASE),
    re.compile(r"system prompt", re.IGNORECASE),
    re.compile(r"you are now ", re.IGNORECASE),
    re.compile(r"\bcurl\s+[^|]*?\|\s*(?:bash|sh)", re.IGNORECASE),
    re.compile(r"\bwget\s+[^|]*?\|\s*(?:bash|sh)", re.IGNORECASE),
    re.compile(r"[​-‏‪-‮﻿]"),  # zero-width / RTL overrides
]


def _scan_log_content(content: str) -> str | None:
    """Return a reason string if `content` looks like prompt injection /
    secret exfil / hidden Unicode, else None.

    Borrowed shape from Hermes' _scan_memory_content. Not exhaustive; raises
    the bar without claiming to be a security boundary.
    """
    for pat in _INJECTION_PATTERNS:
        if pat.search(content):
            return f"content rejected: matches pattern {pat.pattern!r}"
    return None


# ---------------------------------------------------------------------------
# Core writes — insert + sweeper + close
# ---------------------------------------------------------------------------


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
) -> None:
    """Open a new task. The dispatch_prompt seeds the log as the first section.

    `dispatch_prompt` is kept on the call signature because that's what the
    central agent passes when spawning outbound work. We embed it in the
    initial log section rather than as a separate column.
    """
    seed = (
        f"## Dispatched {timeout_at.astimezone(timezone.utc):%Y-%m-%dT%H:%M:%SZ}\n"
        f"Brief: {dispatch_prompt}"
    )
    pool = await get_db()
    query = """
        INSERT INTO outbound_tasks (
            task_key, business_id, customer_id, contact_id, contact_name, contact_role,
            initiated_by, log, timeout_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
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
            seed,
            timeout_at,
        )
    _bump_tenant(business_id)


async def close_task(
    task_key: str,
    *,
    reason: str,
    final_log_entry: str | None = None,
) -> bool:
    """Mark a task closed; append a closing section to log.

    Returns False when the task is already closed (idempotent guard).
    """
    section_lines = [
        f"## Closed {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}",
        f"Reason: {reason}",
    ]
    if final_log_entry:
        section_lines.append(final_log_entry)
    section = "\n".join(section_lines)

    pool = await get_db()
    query = """
        UPDATE outbound_tasks
        SET closed_at = NOW(),
            log = CASE WHEN log = '' THEN $2 ELSE log || E'\n\n' || $2 END
        WHERE task_key = $1 AND closed_at IS NULL
        RETURNING business_id
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, task_key, section)
    if row is None:
        return False
    _bump_tenant(row["business_id"])
    return True


async def sweep_timeouts() -> list[dict[str, Any]]:
    """Close every open task whose timeout has elapsed; return what we
    closed so the caller can fire customer-side notifications.

    Returns rows with task_key, business_id, customer_id, contact_id,
    contact_name. Caller decides how to surface to the customer.
    """
    pool = await get_db()
    # NOW() inside SQL keeps the closed_at and the log timestamp aligned to
    # the same moment; doing it python-side would risk skew across rows.
    query = """
        UPDATE outbound_tasks
        SET closed_at = NOW(),
            log = log || E'\n\n## Auto-closed (timeout) ' ||
                  to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SSZ') ||
                  E'\nReason: vendor never replied within window.'
        WHERE closed_at IS NULL
          AND timeout_at < NOW()
        RETURNING task_key, business_id, customer_id, contact_id, contact_name
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    closed = [dict(r) for r in rows]
    bumped: set[UUID] = set()
    for r in closed:
        biz = r["business_id"]
        if biz not in bumped:
            _bump_tenant(biz)
            bumped.add(biz)
    return closed


# ---------------------------------------------------------------------------
# Log mutations — Hermes-style substring CRUD with size cap.
# ---------------------------------------------------------------------------


class LogWriteError(Exception):
    """Raised when a log mutation can't proceed (cap, missing, ambiguous)."""


async def append_to_log(task_key: str, section: str) -> str:
    """Append `section` (markdown) to the task's log. Returns the new full log.

    Raises LogWriteError when:
      - the task is closed (callers should not be appending to closed work)
      - the addition would exceed LOG_HARD_CAP_BYTES
      - the section content trips the injection scanner
    """
    if reason := _scan_log_content(section):
        raise LogWriteError(reason)

    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT business_id, log, closed_at FROM outbound_tasks WHERE task_key = $1",
            task_key,
        )
        if row is None:
            raise LogWriteError(f"unknown task_key {task_key}")
        if row["closed_at"] is not None:
            raise LogWriteError("task_closed")
        current = row["log"] or ""
        # +2 for the "\n\n" separator we'll add when current is non-empty.
        next_size = len(current.encode("utf-8")) + len(section.encode("utf-8")) + (2 if current else 0)
        if next_size > LOG_HARD_CAP_BYTES:
            raise LogWriteError(
                f"log_cap_exceeded: would be {next_size} bytes; cap is {LOG_HARD_CAP_BYTES}. "
                "Compact older sections via update_task_log(action='replace' or 'remove') first."
            )
        new_log = section if not current else f"{current}\n\n{section}"
        await conn.execute(
            "UPDATE outbound_tasks SET log = $2 WHERE task_key = $1",
            task_key,
            new_log,
        )
    _bump_tenant(row["business_id"])
    return new_log


async def replace_in_log(task_key: str, old_text: str, new_text: str) -> str:
    """Replace exactly one occurrence of `old_text` with `new_text`.

    Raises LogWriteError when:
      - task is closed / unknown
      - old_text is missing
      - old_text appears multiple times (ambiguous — agent must be more specific)
      - new_text fails the injection scanner
      - the replacement would exceed the cap
    """
    if reason := _scan_log_content(new_text):
        raise LogWriteError(reason)

    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT business_id, log, closed_at FROM outbound_tasks WHERE task_key = $1",
            task_key,
        )
        if row is None:
            raise LogWriteError(f"unknown task_key {task_key}")
        if row["closed_at"] is not None:
            raise LogWriteError("task_closed")
        current = row["log"] or ""
        occurrences = current.count(old_text)
        if occurrences == 0:
            raise LogWriteError("old_text_not_found")
        if occurrences > 1:
            raise LogWriteError(
                f"old_text_ambiguous: matches {occurrences} positions; "
                "include more surrounding context to make it unique."
            )
        new_log = current.replace(old_text, new_text, 1)
        if len(new_log.encode("utf-8")) > LOG_HARD_CAP_BYTES:
            raise LogWriteError("log_cap_exceeded after replace")
        await conn.execute(
            "UPDATE outbound_tasks SET log = $2 WHERE task_key = $1",
            task_key,
            new_log,
        )
    _bump_tenant(row["business_id"])
    return new_log


async def remove_from_log(task_key: str, text: str) -> str:
    """Remove exactly one occurrence of `text` from the log."""
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT business_id, log, closed_at FROM outbound_tasks WHERE task_key = $1",
            task_key,
        )
        if row is None:
            raise LogWriteError(f"unknown task_key {task_key}")
        if row["closed_at"] is not None:
            raise LogWriteError("task_closed")
        current = row["log"] or ""
        occurrences = current.count(text)
        if occurrences == 0:
            raise LogWriteError("text_not_found")
        if occurrences > 1:
            raise LogWriteError(
                f"text_ambiguous: matches {occurrences} positions; "
                "include more surrounding context to make it unique."
            )
        # Strip exactly one block + collapse double-blank-lines around removal.
        new_log = current.replace(text, "", 1)
        new_log = re.sub(r"\n{3,}", "\n\n", new_log).strip()
        await conn.execute(
            "UPDATE outbound_tasks SET log = $2 WHERE task_key = $1",
            task_key,
            new_log,
        )
    _bump_tenant(row["business_id"])
    return new_log


async def append_if_open_and_not_recent_dup(
    task_key: str, section: str
) -> tuple[bool, str | None]:
    """Append `section` only if (a) the task is open and (b) the same
    relay text doesn't already appear in the last 5 sections.

    Used by share_update to enforce idempotency past the inbox dedup TTL:
    if the agent re-fires identical relay content for the same task, we
    skip both the log append and the customer fan-out.

    Returns (was_appended, skip_reason). Skip reasons:
      - 'task_closed' (race with close_task / sweeper)
      - 'duplicate_recent_relay'
      - None (when was_appended is True)
    """
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT business_id, log, closed_at FROM outbound_tasks WHERE task_key = $1",
            task_key,
        )
        if row is None:
            return False, "unknown_task_key"
        if row["closed_at"] is not None:
            return False, "task_closed"
        current = row["log"] or ""

        # Cheap dup check: scan the trailing 1500 chars (≈ last few sections)
        # for the exact `section` body. The agent's relay text is the unique
        # part; section header includes a timestamp so headers always differ.
        # Strip the timestamped header line for comparison.
        section_body = "\n".join(section.split("\n")[1:]).strip()
        if section_body and section_body in current[-1500:]:
            return False, "duplicate_recent_relay"

        next_size = len(current.encode("utf-8")) + len(section.encode("utf-8")) + (2 if current else 0)
        if next_size > LOG_HARD_CAP_BYTES:
            return False, "log_cap_exceeded"

        new_log = section if not current else f"{current}\n\n{section}"
        await conn.execute(
            "UPDATE outbound_tasks SET log = $2 WHERE task_key = $1",
            task_key,
            new_log,
        )
    _bump_tenant(row["business_id"])
    return True, None


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def get_by_key(task_key: str) -> OutboundTaskRow | None:
    pool = await get_db()
    query = f"SELECT {_COLUMNS} FROM outbound_tasks WHERE task_key = $1"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, task_key)
    return OutboundTaskRow(**dict(row)) if row else None


def _excerpt(log: str) -> str:
    if len(log) <= LOG_EXCERPT_TAIL_CHARS:
        return log
    return "…" + log[-LOG_EXCERPT_TAIL_CHARS:]


async def list_open_tasks_by_contact(
    business_id: UUID,
    contact_id: UUID,
) -> list[OutboundTaskSummary]:
    """All open tasks for this contact, newest first.

    The manifest the outbound agent reads on every reply turn. Filter is
    `closed_at IS NULL` only — no state machine, no grace window.
    """
    pool = await get_db()
    query = """
        SELECT task_key, contact_role, log, dispatched_at, customer_id
        FROM outbound_tasks
        WHERE business_id = $1
          AND contact_id  = $2
          AND closed_at IS NULL
        ORDER BY dispatched_at DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id, contact_id)
    return [
        OutboundTaskSummary(
            task_key=r["task_key"],
            contact_role=r["contact_role"],
            log_excerpt=_excerpt(r["log"] or ""),
            dispatched_at=r["dispatched_at"],
            customer_id=r["customer_id"],
        )
        for r in rows
    ]


async def get_pending_for_customer(
    business_id: UUID, customer_id: UUID
) -> list[OutboundTaskRow]:
    """Customer-initiated tasks still open — preserved for central agent
    deps construction (mirrors today's API for backwards compat)."""
    pool = await get_db()
    query = f"""
        SELECT {_COLUMNS}
        FROM outbound_tasks
        WHERE business_id = $1
          AND customer_id = $2
          AND initiated_by = 'customer'
          AND closed_at IS NULL
        ORDER BY dispatched_at
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id, customer_id)
    return [OutboundTaskRow(**dict(row)) for row in rows]


async def list_recent_for_customer(
    business_id: UUID,
    customer_id: UUID,
    *,
    limit: int = 20,
) -> list[OutboundTaskRow]:
    """All tasks (open + closed) for this customer, newest first."""
    pool = await get_db()
    query = f"""
        SELECT {_COLUMNS}
        FROM outbound_tasks
        WHERE business_id = $1
          AND customer_id = $2
        ORDER BY dispatched_at DESC
        LIMIT $3
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id, customer_id, limit)
    return [OutboundTaskRow(**dict(row)) for row in rows]


# ---------------------------------------------------------------------------
# bm25 search — find_tasks
# ---------------------------------------------------------------------------


@dataclass
class _TenantIndex:
    version: int
    rows: list[OutboundTaskRow]
    retriever: Any  # bm25s.BM25


_indexes: dict[UUID, _TenantIndex] = {}
_lock = threading.Lock()
_REDIS_VERSION_KEY_PREFIX = "outbound_tasks:idx:version:"


def _bump_tenant(business_id: UUID) -> int:
    """Invalidate this tenant's bm25 cache. Returns the new version.

    Increments a Redis counter so sibling uvicorn workers see the bump on
    their next find_tasks call. Falls back silently to local-only when
    Redis is unavailable.
    """
    key = f"{_REDIS_VERSION_KEY_PREFIX}{business_id}"
    try:
        return int(redis_conn._client.incr(key))
    except Exception:
        logger.exception("failed to bump bm25 version in redis biz=%s", business_id)
        # Local fallback: bump a process-local counter so this worker
        # at least invalidates its own cache.
        with _lock:
            cached = _indexes.get(business_id)
            if cached is not None:
                cached.version += 1
            return cached.version if cached else 1


def _current_version(business_id: UUID) -> int:
    key = f"{_REDIS_VERSION_KEY_PREFIX}{business_id}"
    try:
        raw = redis_conn._client.get(key)
        return int(raw) if raw is not None else 0
    except Exception:
        return 0


def _doc_text(row: OutboundTaskRow) -> str:
    """Text bm25 indexes for one task. Includes contact label so queries
    naming the vendor still rank that task even when log content alone
    doesn't carry the name."""
    return f"{row.contact_role} {row.contact_name} {row.log}"


def _recency_weight(row: OutboundTaskRow) -> float:
    anchor = row.closed_at or row.dispatched_at
    age_days = max(
        (datetime.now(timezone.utc) - anchor).total_seconds() / 86400.0, 0.0
    )
    return math.exp(-age_days * math.log(2) / _RECENCY_HALFLIFE_DAYS)


async def _load_or_build_index(business_id: UUID) -> _TenantIndex | None:
    current = _current_version(business_id)
    with _lock:
        cached = _indexes.get(business_id)
        if cached is not None and cached.version == current:
            return cached

    cutoff = datetime.now(timezone.utc) - timedelta(days=_FIND_TASKS_CUTOFF_DAYS)
    pool = await get_db()
    query = f"""
        SELECT {_COLUMNS}
        FROM outbound_tasks
        WHERE business_id = $1
          AND (closed_at IS NULL OR closed_at > $2)
        ORDER BY COALESCE(closed_at, dispatched_at) DESC
        LIMIT $3
    """
    async with pool.acquire() as conn:
        raw_rows = await conn.fetch(query, business_id, cutoff, _BM25_INDEX_DOC_LIMIT)
    rows = [OutboundTaskRow(**dict(r)) for r in raw_rows]
    if not rows:
        return None

    corpus_tokens = bm25s.tokenize(
        [_doc_text(r) for r in rows], show_progress=False
    )
    retriever = bm25s.BM25()
    retriever.index(corpus_tokens, show_progress=False)

    index = _TenantIndex(version=current, rows=rows, retriever=retriever)
    with _lock:
        _indexes[business_id] = index
    return index


async def find_tasks(
    business_id: UUID,
    query: str,
    *,
    customer_id: UUID | None = None,
    contact_id: UUID | None = None,
    limit: int = 5,
) -> list[OutboundTaskRow]:
    """bm25 over the tenant's task logs. Recency-decayed, score-floored.

    Optional `customer_id` / `contact_id` filters narrow the result post-
    ranking — corpus is still tenant-wide so a customer's tasks compete on
    relevance with siblings.
    """
    if not query.strip():
        return []
    index = await _load_or_build_index(business_id)
    if index is None:
        return []

    query_tokens = bm25s.tokenize(query, show_progress=False)
    k = min(len(index.rows), max(limit * 4, 24))
    hit_ids, hit_scores = index.retriever.retrieve(
        query_tokens, k=k, show_progress=False
    )
    if hasattr(hit_ids, "shape") and len(hit_ids.shape) == 2:
        hit_ids = hit_ids[0]
        hit_scores = hit_scores[0]

    scored: list[tuple[float, OutboundTaskRow]] = []
    for doc_idx, raw in zip(hit_ids, hit_scores):
        idx = int(doc_idx)
        if idx < 0 or idx >= len(index.rows):
            continue
        row = index.rows[idx]
        if customer_id is not None and row.customer_id != customer_id:
            continue
        if contact_id is not None and row.contact_id != contact_id:
            continue
        weighted = float(raw) * _recency_weight(row)
        if weighted < _SCORE_FLOOR:
            continue
        scored.append((weighted, row))

    scored.sort(key=lambda kv: kv[0], reverse=True)
    return [row for _, row in scored[:limit]]
