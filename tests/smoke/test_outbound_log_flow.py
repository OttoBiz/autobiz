"""End-to-end smoke for the log-based outbound flow.

Drives every code path the TUI / WhatsApp would: dispatch → manifest →
share_update → log mutations → close_task → find_tasks → sweeper. Hits
real Postgres + real Redis + real bm25; no mocks except the channel send
(which we replace with an in-memory recorder so we can assert what would
have gone to the vendor / customer).

Run prerequisites — both ports must be reachable:
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ottobiz
    REDIS_URL=redis://:redispassword@localhost:6379/0

Bring them up via the project compose:
    cd app && docker compose up -d postgres redis

Then from the repo root:
    pytest tests/smoke/test_outbound_log_flow.py -xvs
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

# Ensure app/ is importable when running from repo root.
_APP = Path(__file__).resolve().parents[2] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

# Defaults so import-time module loads work; overridden by env when running.
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "redispassword")
os.environ.setdefault(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ottobiz"
)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def db_ready():
    """Apply migrations + seed minimum tenancy. Skip the whole module if
    Postgres or Redis aren't reachable so the suite is friendly when run
    outside the smoke environment."""
    try:
        from backend.db.connection import get_db, init_db
        from backend.db.populate import _run_migrations
    except Exception as exc:
        pytest.skip(f"app imports unavailable: {exc}")

    try:
        await init_db()
        pool = await get_db()
    except Exception as exc:
        pytest.skip(f"postgres not reachable: {exc}")

    try:
        await _run_migrations(pool)
    except Exception as exc:
        pytest.skip(f"migrations failed (likely DB perms): {exc}")

    biz_id = uuid4()
    cust_id = uuid4()
    contact_id = uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO businesses (id, name, business_type) VALUES ($1, $2, 'fashion')",
            biz_id, "Smoke Biz",
        )
        await conn.execute(
            "INSERT INTO users (id, full_name, phone_number) VALUES ($1, $2, $3)",
            cust_id, "Alice Smoke", f"+234{uuid4().hex[:10]}",
        )
        await conn.execute(
            """
            INSERT INTO contacts (id, business_id, name, role, channel, channel_user_id)
            VALUES ($1, $2, $3, $4, 'console', $5)
            """,
            contact_id, biz_id, "Vendor X", "vendor", f"vendor-{uuid4().hex[:6]}",
        )

    yield {"business_id": biz_id, "customer_id": cust_id, "contact_id": contact_id}

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM outbound_tasks WHERE business_id = $1", biz_id)
        await conn.execute("DELETE FROM contacts WHERE id = $1", contact_id)
        await conn.execute("DELETE FROM users WHERE id = $1", cust_id)
        await conn.execute("DELETE FROM businesses WHERE id = $1", biz_id)


@pytest.mark.asyncio(loop_scope="module")
async def test_full_log_flow(db_ready, monkeypatch):
    """Walk the canonical lifecycle: dispatch → relay → amendment → close
    → search-finds-closed-task. Every step verified against real DB state.
    """
    from backend.db import outbound_ledger
    from backend.chatbot.agents import outbound

    biz_id: UUID = db_ready["business_id"]
    customer_id: UUID = db_ready["customer_id"]
    contact_id: UUID = db_ready["contact_id"]

    # 1. Insert a task directly via the ledger (the outbound_agent run is
    #    LLM-bound and not part of the smoke). This proves the seeding +
    #    log shape match what `dispatch()` does.
    task_key = uuid4().hex
    timeout_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await outbound_ledger.insert_task(
        task_key=task_key,
        business_id=biz_id,
        customer_id=customer_id,
        initiated_by="customer",
        dispatch_prompt="confirm Oxford 15 stock and price",
        timeout_at=timeout_at,
        contact_id=contact_id,
        contact_name="Vendor X",
        contact_role="vendor",
    )

    row = await outbound_ledger.get_by_key(task_key)
    assert row is not None
    assert row.closed_at is None
    assert "## Dispatched " in row.log
    assert "confirm Oxford 15 stock and price" in row.log

    # 2. Manifest filter — only open tasks, with log_excerpt.
    manifest = await outbound_ledger.list_open_tasks_by_contact(biz_id, contact_id)
    assert len(manifest) == 1
    assert manifest[0].task_key == task_key
    assert "Oxford 15" in manifest[0].log_excerpt

    # 3. share_update equivalent: append a relay section.
    relay_1 = "## Relayed to customer 2026-05-08T11:42:00Z\nVendor confirmed size 15 in stock at NGN 30,000."
    appended, reason = await outbound_ledger.append_if_open_and_not_recent_dup(
        task_key, relay_1
    )
    assert appended is True
    assert reason is None

    # 4. Vendor amendment — second share_update with different content.
    relay_2 = "## Relayed to customer 2026-05-08T14:20:00Z\nUpdate: only 1 pair of size 15 left."
    appended_2, _ = await outbound_ledger.append_if_open_and_not_recent_dup(
        task_key, relay_2
    )
    assert appended_2 is True

    # 5. Identical relay re-fired — must dedup at log layer.
    relay_2_dup_diff_ts = "## Relayed to customer 2026-05-08T14:25:00Z\nUpdate: only 1 pair of size 15 left."
    appended_3, dup_reason = await outbound_ledger.append_if_open_and_not_recent_dup(
        task_key, relay_2_dup_diff_ts
    )
    assert appended_3 is False
    assert dup_reason == "duplicate_recent_relay"

    # Sanity: log carries both relays, only once each.
    row = await outbound_ledger.get_by_key(task_key)
    assert row.log.count("Vendor confirmed size 15 in stock at NGN 30,000.") == 1
    assert row.log.count("only 1 pair of size 15 left.") == 1

    # 6. Hermes-style edit — replace a section.
    new_log = await outbound_ledger.replace_in_log(
        task_key,
        "Update: only 1 pair of size 15 left.",
        "Update: only 1 pair left; vendor will hold for 24h.",
    )
    assert "hold for 24h" in new_log
    assert "1 pair of size 15 left." not in new_log

    # 7. find_tasks bm25 — closed-tasks-and-open both indexed.
    rows = await outbound_ledger.find_tasks(biz_id, "Oxford 15 in stock", limit=5)
    assert any(r.task_key == task_key for r in rows)

    # 8. close_task explicit close.
    closed = await outbound_ledger.close_task(
        task_key, reason="customer paid", final_log_entry="Order confirmed end-to-end."
    )
    assert closed is True
    closed_row = await outbound_ledger.get_by_key(task_key)
    assert closed_row.closed_at is not None
    assert "## Closed" in closed_row.log
    assert "customer paid" in closed_row.log

    # 9. Manifest is empty after close (closed_at IS NOT NULL).
    manifest_after = await outbound_ledger.list_open_tasks_by_contact(biz_id, contact_id)
    assert manifest_after == []

    # 10. find_tasks still returns the closed task (within 180-day cutoff).
    rows = await outbound_ledger.find_tasks(biz_id, "Oxford order paid", limit=5)
    assert any(r.task_key == task_key for r in rows)

    # 11. Closing again is a no-op (idempotent guard).
    re_closed = await outbound_ledger.close_task(task_key, reason="redundant")
    assert re_closed is False

    # 12. Append on a closed task is rejected (race protection).
    with pytest.raises(outbound_ledger.LogWriteError, match="task_closed"):
        await outbound_ledger.append_to_log(task_key, "## post-close attempt")

    appended_post_close, post_reason = (
        await outbound_ledger.append_if_open_and_not_recent_dup(
            task_key, "## post-close attempt 2"
        )
    )
    assert appended_post_close is False
    assert post_reason == "task_closed"


@pytest.mark.asyncio(loop_scope="module")
async def test_sweeper_closes_expired_and_notifies_customer(db_ready, monkeypatch):
    """Timeout sweeper: sets closed_at, appends auto-close log entry,
    pushes a customer-side system_event so the customer doesn't get ghosted.
    """
    from backend.db import outbound_ledger
    from backend.chatbot import sweeper

    biz_id = db_ready["business_id"]
    customer_id = db_ready["customer_id"]
    contact_id = db_ready["contact_id"]

    # Insert a task that's already past its timeout.
    task_key = uuid4().hex
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    await outbound_ledger.insert_task(
        task_key=task_key,
        business_id=biz_id,
        customer_id=customer_id,
        initiated_by="customer",
        dispatch_prompt="vendor will time out",
        timeout_at=past,
        contact_id=contact_id,
        contact_name="Vendor X",
        contact_role="vendor",
    )

    # Capture the customer-side notify rather than letting it run a real
    # central agent.
    notified: list[dict] = []

    async def _capture(**kwargs):
        notified.append(kwargs)

    monkeypatch.setattr(sweeper, "_notify_customer_of_timeout", _capture)

    closed = await sweeper.sweep_once()
    keys = [r["task_key"] for r in closed]
    assert task_key in keys

    row = await outbound_ledger.get_by_key(task_key)
    assert row.closed_at is not None
    assert "Auto-closed (timeout)" in row.log
    assert "vendor never replied within window" in row.log

    # Customer notification fired with the right ids.
    matching = [n for n in notified if n["task_key"] == task_key]
    assert len(matching) == 1
    assert matching[0]["customer_id"] == customer_id
    assert matching[0]["contact_name"] == "Vendor X"


@pytest.mark.asyncio(loop_scope="module")
async def test_find_tasks_recency_and_score_floor(db_ready):
    """Two tasks for the same customer; query matches the recent one
    distinctively. Stale + irrelevant tasks don't surface at the floor."""
    from backend.db import outbound_ledger

    biz_id = db_ready["business_id"]
    customer_id = db_ready["customer_id"]
    contact_id = db_ready["contact_id"]

    fresh_key = uuid4().hex
    stale_key = uuid4().hex
    await outbound_ledger.insert_task(
        task_key=fresh_key,
        business_id=biz_id,
        customer_id=customer_id,
        initiated_by="customer",
        dispatch_prompt="ankara fabric purple yards delivery to Coker",
        timeout_at=datetime.now(timezone.utc) + timedelta(hours=1),
        contact_id=contact_id,
        contact_name="Vendor X",
        contact_role="vendor",
    )
    await outbound_ledger.insert_task(
        task_key=stale_key,
        business_id=biz_id,
        customer_id=customer_id,
        initiated_by="customer",
        dispatch_prompt="leather Oxford laces request",
        timeout_at=datetime.now(timezone.utc) + timedelta(hours=1),
        contact_id=contact_id,
        contact_name="Vendor X",
        contact_role="vendor",
    )

    # Query that matches the fresh task distinctly.
    rows = await outbound_ledger.find_tasks(biz_id, "ankara purple yards", limit=5)
    keys = [r.task_key for r in rows]
    assert fresh_key in keys
    # Stale leather-Oxford row shouldn't outrank when query is ankara-specific.
    if rows:
        assert rows[0].task_key == fresh_key

    # Garbage query → score floor returns nothing.
    junk = await outbound_ledger.find_tasks(biz_id, "qrxqrx zzzqq", limit=5)
    assert junk == []
