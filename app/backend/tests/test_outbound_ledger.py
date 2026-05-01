"""Outbound ledger accessor tests.

The Docker test database is not available in this environment (no docker
daemon, no local Postgres on :5432). Tests therefore mock the asyncpg
connection pool and verify SQL strings, parameter ordering, the
mark_completed validation rule, and rowcount-derived return values.
Replace with a real-DB conftest fixture once the test harness lands.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.db import outbound_ledger


def _normalize(sql: str) -> str:
    return " ".join(sql.split())


class _FakeConn:
    def __init__(self) -> None:
        self.execute = AsyncMock(return_value="UPDATE 1")
        self.fetch = AsyncMock(return_value=[])
        self.fetchrow = AsyncMock(return_value=None)


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def acquire(self) -> Any:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=self._conn)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm


@pytest.fixture
def conn() -> _FakeConn:
    return _FakeConn()


@pytest.fixture(autouse=True)
def patch_pool(monkeypatch, conn):
    pool = _FakePool(conn)

    async def fake_get_db() -> _FakePool:
        return pool

    monkeypatch.setattr(outbound_ledger, "get_db", fake_get_db)
    return pool


@pytest.mark.asyncio
async def test_insert_task_sql_and_params(conn):
    business_id = uuid4()
    customer_id = uuid4()
    contact_id = uuid4()
    timeout_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    await outbound_ledger.insert_task(
        task_key="tk-1",
        business_id=business_id,
        customer_id=customer_id,
        initiated_by="customer",
        dispatch_prompt="ask vendor",
        timeout_at=timeout_at,
        contact_id=contact_id,
        contact_name="Vendor X",
        contact_role="vendor",
        summary="ask vendor about stock",
    )

    sql, *params = conn.execute.call_args.args
    assert "INSERT INTO outbound_tasks" in sql
    assert _normalize(sql).startswith(
        "INSERT INTO outbound_tasks ( task_key, business_id, customer_id, "
        "contact_id, contact_name, contact_role, initiated_by, dispatch_prompt, "
        "summary, timeout_at )"
    )
    assert "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)" in _normalize(sql)
    assert params == [
        "tk-1",
        business_id,
        customer_id,
        contact_id,
        "Vendor X",
        "vendor",
        "customer",
        "ask vendor",
        "ask vendor about stock",
        timeout_at,
    ]


@pytest.mark.asyncio
async def test_mark_running_sql_and_idempotency_flag(conn):
    conn.execute.return_value = "UPDATE 1"
    assert await outbound_ledger.mark_running("tk-1") is True

    sql = conn.execute.call_args.args[0]
    assert "UPDATE outbound_tasks" in sql
    assert "SET state = 'running'" in sql
    assert "WHERE task_key = $1 AND state = 'queued'" in _normalize(sql)

    conn.execute.return_value = "UPDATE 0"
    assert await outbound_ledger.mark_running("tk-1") is False


@pytest.mark.asyncio
async def test_mark_completed_round_trip_returns_true(conn):
    conn.execute.return_value = "UPDATE 1"

    result = await outbound_ledger.mark_completed(
        "tk-1", customer_context="hello", system_context=None
    )

    assert result is True
    sql, *params = conn.execute.call_args.args
    assert "state = 'succeeded'" in sql
    assert "WHERE task_key = $1 AND state = 'running'" in _normalize(sql)
    assert params == ["tk-1", "hello", None]


@pytest.mark.asyncio
async def test_mark_completed_idempotent_second_call_returns_false(conn):
    conn.execute.return_value = "UPDATE 0"

    result = await outbound_ledger.mark_completed(
        "tk-1", customer_context="hello", system_context=None
    )

    assert result is False


@pytest.mark.asyncio
async def test_mark_completed_validates_at_least_one_context():
    with pytest.raises(ValueError):
        await outbound_ledger.mark_completed("tk-1", customer_context=None, system_context=None)
    with pytest.raises(ValueError):
        await outbound_ledger.mark_completed("tk-1", customer_context="", system_context="")


@pytest.mark.asyncio
async def test_mark_failed_sets_failed_state(conn):
    conn.execute.return_value = "UPDATE 1"

    assert await outbound_ledger.mark_failed("tk-1", "vendor unreachable") is True

    sql, *params = conn.execute.call_args.args
    assert "state = 'failed'" in sql
    assert "WHERE task_key = $1 AND state = 'running'" in _normalize(sql)
    assert params == ["tk-1", "vendor unreachable"]


@pytest.mark.asyncio
async def test_mark_cancelled_allows_queued_or_running(conn):
    conn.execute.return_value = "UPDATE 1"

    assert await outbound_ledger.mark_cancelled("tk-1") is True

    sql = conn.execute.call_args.args[0]
    assert "state = 'cancelled'" in sql
    assert "state IN ('queued', 'running')" in _normalize(sql)


@pytest.mark.asyncio
async def test_get_by_key_returns_row_model(conn):
    business_id = uuid4()
    customer_id = uuid4()
    contact_id = uuid4()
    now = datetime.now(timezone.utc)
    conn.fetchrow.return_value = {
        "task_key": "tk-1",
        "business_id": business_id,
        "customer_id": customer_id,
        "contact_id": contact_id,
        "contact_name": "Vendor X",
        "contact_role": "vendor",
        "initiated_by": "customer",
        "dispatch_prompt": "ask vendor",
        "summary": "ask vendor",
        "state": "queued",
        "customer_context": None,
        "system_context": None,
        "dispatched_at": now,
        "resolved_at": None,
        "timeout_at": now + timedelta(minutes=5),
    }

    row = await outbound_ledger.get_by_key("tk-1")

    assert row is not None
    assert row.task_key == "tk-1"
    assert row.business_id == business_id
    assert row.state == "queued"

    sql, *params = conn.fetchrow.call_args.args
    assert "FROM outbound_tasks WHERE task_key = $1" in _normalize(sql)
    assert params == ["tk-1"]


@pytest.mark.asyncio
async def test_get_by_key_returns_none_when_missing(conn):
    conn.fetchrow.return_value = None
    assert await outbound_ledger.get_by_key("missing") is None


@pytest.mark.asyncio
async def test_get_pending_filters_to_customer_initiated(conn):
    business_id = uuid4()
    customer_id = uuid4()
    conn.fetch.return_value = []

    result = await outbound_ledger.get_pending_for_customer(business_id, customer_id)
    assert result == []

    sql, *params = conn.fetch.call_args.args
    norm = _normalize(sql)
    assert "WHERE business_id = $1" in norm
    assert "AND customer_id = $2" in norm
    assert "AND initiated_by = 'customer'" in norm
    assert "AND state IN ('queued', 'running')" in norm
    assert "ORDER BY dispatched_at" in norm
    assert params == [business_id, customer_id]


@pytest.mark.asyncio
async def test_get_resolved_since_uses_cursor(conn):
    business_id = uuid4()
    customer_id = uuid4()
    cursor = datetime(2026, 4, 22, tzinfo=timezone.utc)
    conn.fetch.return_value = []

    await outbound_ledger.get_resolved_since(business_id, customer_id, cursor)

    sql, *params = conn.fetch.call_args.args
    norm = _normalize(sql)
    assert "AND customer_context IS NOT NULL" in norm
    assert "AND resolved_at > COALESCE($3, '-infinity'::timestamptz)" in norm
    assert params == [business_id, customer_id, cursor]


@pytest.mark.asyncio
async def test_get_resolved_since_with_null_cursor(conn):
    business_id = uuid4()
    customer_id = uuid4()
    conn.fetch.return_value = []

    await outbound_ledger.get_resolved_since(business_id, customer_id, None)

    params = conn.fetch.call_args.args[1:]
    assert params == (business_id, customer_id, None)


@pytest.mark.asyncio
async def test_get_state_returns_state_or_none(conn):
    conn.fetchrow.return_value = {"state": "running"}
    assert await outbound_ledger.get_state("tk-1") == "running"

    conn.fetchrow.return_value = None
    assert await outbound_ledger.get_state("missing") is None


@pytest.mark.asyncio
async def test_list_open_tasks_by_contact_returns_empty_when_none(conn):
    conn.fetch.return_value = []
    business_id = uuid4()
    contact_id = uuid4()

    result = await outbound_ledger.list_open_tasks_by_contact(business_id, contact_id)

    assert result == []
    sql, *params = conn.fetch.call_args.args
    norm = _normalize(sql)
    # Projection columns only — not the full _COLUMNS tuple.
    assert "SELECT task_key, contact_role, summary, dispatched_at, customer_id" in norm
    assert "FROM outbound_tasks" in norm
    assert "WHERE business_id = $1" in norm
    assert "AND contact_id = $2" in norm
    assert "AND state = 'running'" in norm
    assert "ORDER BY dispatched_at DESC" in norm
    # NOT a get_by_key — should not be limited to 1.
    assert "LIMIT" not in norm
    assert params == [business_id, contact_id]


@pytest.mark.asyncio
async def test_list_open_tasks_by_contact_returns_summaries_in_order(conn):
    business_id = uuid4()
    customer_id_a = uuid4()
    customer_id_b = uuid4()
    now = datetime.now(timezone.utc)
    earlier = now - timedelta(minutes=10)
    conn.fetch.return_value = [
        {
            "task_key": "tk-newer",
            "contact_role": "vendor",
            "summary": "ask about ankara stock",
            "dispatched_at": now,
            "customer_id": customer_id_a,
        },
        {
            "task_key": "tk-older",
            "contact_role": "vendor",
            "summary": "confirm shipping window",
            "dispatched_at": earlier,
            "customer_id": customer_id_b,
        },
    ]

    rows = await outbound_ledger.list_open_tasks_by_contact(business_id, uuid4())

    assert len(rows) == 2
    assert all(isinstance(r, outbound_ledger.OutboundTaskSummary) for r in rows)
    assert rows[0].task_key == "tk-newer"
    assert rows[0].summary == "ask about ankara stock"
    assert rows[1].task_key == "tk-older"


@pytest.mark.asyncio
async def test_sweep_timeouts_returns_task_keys(conn):
    conn.fetch.return_value = [{"task_key": "tk-a"}, {"task_key": "tk-b"}]

    keys = await outbound_ledger.sweep_timeouts()

    assert keys == ["tk-a", "tk-b"]
    sql = conn.fetch.call_args.args[0]
    norm = _normalize(sql)
    assert "UPDATE outbound_tasks" in norm
    assert "SET state = 'timed_out'" in norm
    assert "WHERE state IN ('queued', 'running') AND timeout_at < NOW()" in norm
    assert "RETURNING task_key" in norm
