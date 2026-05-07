"""Multiparty event ledger tests.

Covers the SQL/parameter shape for events.py, recency-weighted bm25s
clustering in events_search.py, and the find_customer_context tool wiring.
The Postgres pool is faked in-process; bm25s is exercised for real (it's a
small pure-python package) but the per-tenant index is rebuilt from a
fixture-controlled doc list rather than the DB.
"""

from __future__ import annotations

import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "")

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from backend.db import events as events_db
from backend.db import events_search


# ---------------------------------------------------------------------------
# events.py — SQL shape + parameter ordering
# ---------------------------------------------------------------------------


def _normalize(sql: str) -> str:
    return " ".join(sql.split())


class _FakeConn:
    def __init__(self) -> None:
        self.execute = AsyncMock(return_value="INSERT 0 1")
        self.fetch = AsyncMock(return_value=[])
        self.fetchrow = AsyncMock(return_value={"id": 42})


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

    monkeypatch.setattr(events_db, "get_db", fake_get_db)
    return pool


@pytest.mark.asyncio
async def test_insert_event_inserts_full_row_and_returns_id(conn):
    biz = uuid4()
    customer_id = uuid4()
    contact_id = uuid4()

    new_id = await events_db.insert_event(
        business_id=biz,
        actor="business",
        direction="out",
        thread_id=f"contact:{contact_id}",
        content="hi vendor",
        customer_id=customer_id,
        contact_id=contact_id,
        task_key="tk-x",
        provider_message_id="wamid.ABC",
    )

    assert new_id == 42
    sql, *params = conn.fetchrow.call_args.args
    norm = _normalize(sql)
    assert "INSERT INTO events" in norm
    assert (
        "( business_id, customer_id, contact_id, task_key, thread_id, "
        "actor, direction, content, provider_message_id )"
    ) in norm
    assert "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)" in norm
    assert "RETURNING id" in norm
    assert params == [
        biz,
        customer_id,
        contact_id,
        "tk-x",
        f"contact:{contact_id}",
        "business",
        "out",
        "hi vendor",
        "wamid.ABC",
    ]


@pytest.mark.asyncio
async def test_insert_event_rejects_blank_content():
    with pytest.raises(ValueError):
        await events_db.insert_event(
            business_id=uuid4(),
            actor="contact",
            direction="in",
            thread_id="contact:x",
            content="",
        )
    with pytest.raises(ValueError):
        await events_db.insert_event(
            business_id=uuid4(),
            actor="contact",
            direction="in",
            thread_id="contact:x",
            content="   ",
        )


@pytest.mark.asyncio
async def test_list_recent_for_customer_filters_and_orders(conn):
    biz = uuid4()
    customer_id = uuid4()
    conn.fetch.return_value = []

    await events_db.list_recent_for_customer(biz, customer_id, limit=7)

    sql, *params = conn.fetch.call_args.args
    norm = _normalize(sql)
    assert "WHERE business_id = $1 AND customer_id = $2" in norm
    assert "ORDER BY created_at DESC" in norm
    assert "LIMIT $3" in norm
    assert params == [biz, customer_id, 7]


# ---------------------------------------------------------------------------
# events_search.py — bm25s clustering with recency weighting
# ---------------------------------------------------------------------------


def _row(
    *,
    customer_id: UUID | None,
    content: str,
    actor: str = "contact",
    direction: str = "in",
    age_minutes: int = 1,
    business_id: UUID | None = None,
) -> events_db.EventRow:
    return events_db.EventRow(
        id=int.from_bytes(uuid4().bytes[:6], "big"),
        business_id=business_id or uuid4(),
        customer_id=customer_id,
        contact_id=None,
        task_key=None,
        thread_id="t",
        actor=actor,  # type: ignore[arg-type]
        direction=direction,  # type: ignore[arg-type]
        content=content,
        provider_message_id=None,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
    )


@pytest.fixture
def reset_search_caches():
    events_search._versions.clear()
    events_search._indexes.clear()
    yield
    events_search._versions.clear()
    events_search._indexes.clear()


@pytest.mark.asyncio
async def test_find_customer_clusters_groups_hits_by_customer(
    monkeypatch, reset_search_caches
):
    biz = uuid4()
    customer_a = uuid4()
    customer_b = uuid4()

    # Customer A has multiple matches; B has one weak match. A should win
    # cluster ranking even though B has fewer total docs (max-pool, not sum).
    docs = [
        _row(customer_id=customer_a, content="oxford shoes size 15 delivery", age_minutes=5),
        _row(customer_id=customer_a, content="please deliver to 1 Justice Coker", age_minutes=4),
        _row(customer_id=customer_b, content="ankara fabric question", age_minutes=3),
        _row(customer_id=None, content="vendor said address noted delivery going out", age_minutes=2),
    ]

    async def fake_list(business_id, *, limit=5000):
        return docs

    monkeypatch.setattr(events_db, "list_recent_for_business", fake_list)

    async def fake_list_for_customer(business_id, customer_id, *, limit=20):
        return [d for d in docs if d.customer_id == customer_id][:limit]

    monkeypatch.setattr(events_db, "list_recent_for_customer", fake_list_for_customer)

    # Stub user + open task lookups so cluster expansion stays in-memory.
    from backend.db import db_utils, outbound_ledger

    async def fake_user(uid):
        return {"id": uid, "name": "Alice" if uid == str(customer_a) else "Bob"}

    monkeypatch.setattr(db_utils, "get_user_by_id", fake_user)
    monkeypatch.setattr(
        outbound_ledger,
        "get_pending_for_customer",
        AsyncMock(return_value=[]),
    )

    events_search.bump_tenant(biz)
    clusters = await events_search.find_customer_clusters(
        biz, "oxford shoes delivery", limit=5
    )

    # A wins cluster #1; B is irrelevant; the unattributed vendor reply
    # comes through as customer_id=None.
    by_id = {c.customer_id: c for c in clusters}
    assert customer_a in by_id
    assert by_id[customer_a].score > 0
    assert by_id[customer_a].customer_name == "Alice"
    # A's score must beat B's weaker match.
    if customer_b in by_id:
        assert by_id[customer_a].score >= by_id[customer_b].score


@pytest.mark.asyncio
async def test_find_customer_clusters_recency_decay(monkeypatch, reset_search_caches):
    """Two equally-matching events for two different customers; the more
    recent one must rank first because of the recency-decay weight."""
    biz = uuid4()
    new_customer = uuid4()
    old_customer = uuid4()

    docs = [
        _row(customer_id=new_customer, content="oxford delivery", age_minutes=10),
        _row(
            customer_id=old_customer,
            content="oxford delivery",
            age_minutes=60 * 24 * 60,  # 60 days old
        ),
    ]

    async def fake_list(business_id, *, limit=5000):
        return docs

    monkeypatch.setattr(events_db, "list_recent_for_business", fake_list)
    monkeypatch.setattr(
        events_db,
        "list_recent_for_customer",
        AsyncMock(return_value=[]),
    )
    from backend.db import db_utils, outbound_ledger

    monkeypatch.setattr(db_utils, "get_user_by_id", AsyncMock(return_value=None))
    monkeypatch.setattr(
        outbound_ledger, "get_pending_for_customer", AsyncMock(return_value=[])
    )

    events_search.bump_tenant(biz)
    clusters = await events_search.find_customer_clusters(biz, "oxford delivery")

    assert clusters[0].customer_id == new_customer


@pytest.mark.asyncio
async def test_find_customer_clusters_returns_empty_on_empty_query(reset_search_caches):
    out = await events_search.find_customer_clusters(uuid4(), "   ")
    assert out == []


@pytest.mark.asyncio
async def test_find_customer_clusters_returns_empty_when_no_events(
    monkeypatch, reset_search_caches
):
    async def fake_list(business_id, *, limit=5000):
        return []

    monkeypatch.setattr(events_db, "list_recent_for_business", fake_list)
    out = await events_search.find_customer_clusters(uuid4(), "anything")
    assert out == []


@pytest.mark.asyncio
async def test_bump_tenant_invalidates_cache(monkeypatch, reset_search_caches):
    biz = uuid4()
    docs_v1 = [_row(customer_id=uuid4(), content="first")]
    docs_v2 = [_row(customer_id=uuid4(), content="second message")]
    state = {"docs": docs_v1}

    async def fake_list(business_id, *, limit=5000):
        return state["docs"]

    monkeypatch.setattr(events_db, "list_recent_for_business", fake_list)
    monkeypatch.setattr(
        events_db, "list_recent_for_customer", AsyncMock(return_value=[])
    )
    from backend.db import db_utils, outbound_ledger

    monkeypatch.setattr(db_utils, "get_user_by_id", AsyncMock(return_value=None))
    monkeypatch.setattr(
        outbound_ledger, "get_pending_for_customer", AsyncMock(return_value=[])
    )

    events_search.bump_tenant(biz)
    first = await events_search.find_customer_clusters(biz, "first")
    assert first  # built v1

    # Swap data and bump — next search must see the new doc.
    state["docs"] = docs_v2
    events_search.bump_tenant(biz)
    second = await events_search.find_customer_clusters(biz, "second")
    assert second
    assert second[0].customer_id == docs_v2[0].customer_id
