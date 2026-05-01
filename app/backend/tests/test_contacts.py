"""Tests for the contacts accessor module.

Mocks the asyncpg pool/connection. Verifies SQL-level guarantees for the
read paths (tenant scoping, role filter, channel filter) and the upsert's
ON CONFLICT shape.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.db import contacts


def _normalize(sql: str) -> str:
    return " ".join(sql.split())


def _row(business_id, name="Acme", role="vendor", channel_user_id="wa-1"):
    now = datetime.now(timezone.utc)
    return {
        "id": uuid4(),
        "business_id": business_id,
        "name": name,
        "role": role,
        "channel": "whatsapp",
        "channel_user_id": channel_user_id,
        "channel_business_id": None,
        "notes": None,
        "created_at": now,
        "updated_at": now,
    }


class _FakeConn:
    def __init__(self) -> None:
        self.fetchrow = AsyncMock(return_value=None)
        self.fetch = AsyncMock(return_value=[])


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

    monkeypatch.setattr(contacts, "get_db", fake_get_db)
    return pool


@pytest.mark.asyncio
async def test_get_by_id_returns_contact_when_present(conn):
    business_id = uuid4()
    conn.fetchrow.return_value = _row(business_id, name="Vendor X")

    result = await contacts.get_by_id(uuid4())

    assert result is not None
    assert result.name == "Vendor X"
    assert result.business_id == business_id


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_missing(conn):
    conn.fetchrow.return_value = None
    assert await contacts.get_by_id(uuid4()) is None


@pytest.mark.asyncio
async def test_get_by_wa_id_is_tenant_scoped_and_whatsapp_only(conn):
    business_id = uuid4()
    conn.fetchrow.return_value = _row(business_id)

    result = await contacts.get_by_wa_id(business_id, "wa-1")

    assert result is not None
    sql, *params = conn.fetchrow.call_args.args
    norm = _normalize(sql)
    assert "FROM contacts" in norm
    assert "business_id = $1" in norm
    assert "channel = 'whatsapp'" in norm
    assert "channel_user_id = $2" in norm
    assert params == [business_id, "wa-1"]


@pytest.mark.asyncio
async def test_list_by_business_no_role_unfiltered(conn):
    business_id = uuid4()
    conn.fetch.return_value = [_row(business_id), _row(business_id, name="B")]

    result = await contacts.list_by_business(business_id, role=None)

    assert len(result) == 2
    sql, *params = conn.fetch.call_args.args
    norm = _normalize(sql)
    assert "FROM contacts WHERE business_id = $1" in norm
    assert " role = " not in norm
    assert params == [business_id]


@pytest.mark.asyncio
async def test_list_by_business_with_role_filters(conn):
    business_id = uuid4()
    conn.fetch.return_value = [_row(business_id, role="vendor")]

    result = await contacts.list_by_business(business_id, role="vendor")

    assert len(result) == 1
    sql, *params = conn.fetch.call_args.args
    norm = _normalize(sql)
    assert "business_id = $1 AND role = $2" in norm
    assert params == [business_id, "vendor"]


@pytest.mark.asyncio
async def test_upsert_uses_on_conflict_update(conn):
    business_id = uuid4()
    conn.fetchrow.return_value = _row(business_id, name="Updated")

    result = await contacts.upsert(
        business_id=business_id,
        name="Updated",
        role="vendor",
        channel="whatsapp",
        channel_user_id="wa-1",
        channel_business_id=None,
        notes="primary",
    )

    assert result.name == "Updated"
    sql, *params = conn.fetchrow.call_args.args
    norm = _normalize(sql)
    assert "INSERT INTO contacts" in norm
    assert "ON CONFLICT (business_id, channel, channel_user_id) DO UPDATE" in norm
    assert "name = EXCLUDED.name" in norm
    assert "role = EXCLUDED.role" in norm
    assert "updated_at = NOW()" in norm
    assert params == [business_id, "Updated", "vendor", "whatsapp", "wa-1", None, "primary"]
