"""channel_identities SQL accessor tests.

Mirrors the asyncpg-mock pattern from test_outbound_ledger.py. Verifies
SQL strings, parameter ordering, and row→model mapping without a real DB.
"""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.chatbot.channels import registry
from backend.chatbot.channels.base import Channel, ChannelIdentity, WindowPolicy
from backend.db import channel_identities


def _normalize(sql: str) -> str:
    return " ".join(sql.split())


class _FakeConn:
    def __init__(self) -> None:
        self.execute = AsyncMock(return_value="INSERT 0 1")
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

    monkeypatch.setattr(channel_identities, "get_db", fake_get_db)
    return pool


@pytest.mark.asyncio
async def test_get_identity_sql_and_params(conn):
    business_id = uuid4()
    customer_id = uuid4()
    conn.fetchrow.return_value = None

    result = await channel_identities.get_identity(
        business_id, customer_id, "whatsapp"
    )

    assert result is None
    sql, *params = conn.fetchrow.call_args.args
    norm = _normalize(sql)
    assert "SELECT business_id, customer_id, channel, channel_user_id, last_inbound_at" in norm
    assert "FROM channel_identities" in norm
    assert "WHERE business_id = $1 AND customer_id = $2 AND channel = $3" in norm
    assert params == [business_id, customer_id, "whatsapp"]


@pytest.mark.asyncio
async def test_get_identity_maps_row(conn):
    business_id = uuid4()
    customer_id = uuid4()
    last = datetime.now(timezone.utc)
    conn.fetchrow.return_value = {
        "business_id": business_id,
        "customer_id": customer_id,
        "channel": "whatsapp",
        "channel_user_id": "2348000",
        "last_inbound_at": last,
    }

    identity = await channel_identities.get_identity(
        business_id, customer_id, "whatsapp"
    )

    assert identity is not None
    assert identity.business_id == str(business_id)
    assert identity.customer_id == str(customer_id)
    assert identity.channel == "whatsapp"
    assert identity.channel_user_id == "2348000"
    assert identity.last_inbound_at == last


@pytest.mark.asyncio
async def test_upsert_identity_sql_and_params(conn):
    business_id = uuid4()
    customer_id = uuid4()
    last = datetime.now(timezone.utc)
    identity = ChannelIdentity(
        business_id=str(business_id),
        customer_id=str(customer_id),
        channel="whatsapp",
        channel_user_id="2348000",
        last_inbound_at=last,
    )

    await channel_identities.upsert_identity(identity)

    sql, *params = conn.execute.call_args.args
    norm = _normalize(sql)
    assert "INSERT INTO channel_identities" in norm
    assert "ON CONFLICT (business_id, customer_id, channel) DO UPDATE SET" in norm
    assert "channel_user_id = EXCLUDED.channel_user_id" in norm
    assert "last_inbound_at = EXCLUDED.last_inbound_at" in norm
    assert params == [
        str(business_id),
        str(customer_id),
        "whatsapp",
        "2348000",
        last,
    ]


@pytest.mark.asyncio
async def test_get_most_recent_identity_sql_and_params(conn):
    business_id = uuid4()
    customer_id = uuid4()
    conn.fetchrow.return_value = None

    result = await channel_identities.get_most_recent_identity(
        business_id, customer_id
    )

    assert result is None
    sql, *params = conn.fetchrow.call_args.args
    norm = _normalize(sql)
    assert "FROM channel_identities" in norm
    assert "WHERE business_id = $1 AND customer_id = $2" in norm
    assert "ORDER BY last_inbound_at DESC NULLS LAST" in norm
    assert "LIMIT 1" in norm
    assert params == [business_id, customer_id]


@pytest.mark.asyncio
async def test_get_most_recent_identity_returns_model(conn):
    business_id = uuid4()
    customer_id = uuid4()
    last = datetime.now(timezone.utc)
    conn.fetchrow.return_value = {
        "business_id": business_id,
        "customer_id": customer_id,
        "channel": "whatsapp",
        "channel_user_id": "2348000",
        "last_inbound_at": last,
    }

    identity = await channel_identities.get_most_recent_identity(
        business_id, customer_id
    )

    assert identity is not None
    assert identity.channel == "whatsapp"
    assert identity.last_inbound_at == last


class _StubChannel(Channel):
    name = "whatsapp"

    def parse_inbound(self, raw: dict):  # pragma: no cover
        raise NotImplementedError

    async def send(self, identity, text):  # pragma: no cover
        raise NotImplementedError

    async def send_template(self, identity, template, vars):  # pragma: no cover
        raise NotImplementedError

    def window_policy(self) -> WindowPolicy:
        return WindowPolicy(
            has_window=True, window_hours=24, out_of_window_behavior="template"
        )


@pytest.fixture
def _reset_registry():
    saved_registry = dict(registry._REGISTRY)
    saved_resolver = registry._identity_resolver
    registry._REGISTRY.clear()
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved_registry)
    registry._identity_resolver = saved_resolver


@pytest.mark.asyncio
async def test_resolver_wired_at_module_import(_reset_registry, conn):
    # Module import registered _resolve_channel_for_customer; resolver
    # maps (business, customer) → most recent identity → registered Channel.
    stub = _StubChannel()
    registry.register(stub)

    business_id = uuid4()
    customer_id = uuid4()
    conn.fetchrow.return_value = {
        "business_id": business_id,
        "customer_id": customer_id,
        "channel": "whatsapp",
        "channel_user_id": "2348000",
        "last_inbound_at": datetime.now(timezone.utc),
    }

    resolved = await registry.get_for_customer(str(business_id), str(customer_id))

    assert resolved is stub


@pytest.mark.asyncio
async def test_resolver_returns_none_when_no_identity(_reset_registry, conn):
    conn.fetchrow.return_value = None

    resolved = await registry.get_for_customer(str(uuid4()), str(uuid4()))

    assert resolved is None


@pytest.mark.asyncio
async def test_resolver_returns_none_when_channel_unregistered(_reset_registry, conn):
    business_id = uuid4()
    customer_id = uuid4()
    conn.fetchrow.return_value = {
        "business_id": business_id,
        "customer_id": customer_id,
        "channel": "slack",
        "channel_user_id": "U123",
        "last_inbound_at": datetime.now(timezone.utc),
    }

    resolved = await registry.get_for_customer(str(business_id), str(customer_id))

    assert resolved is None
