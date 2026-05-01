"""Tests for `whatsapp_resolver.resolve_inbound_sender`.

Single SQL fetchrow call, four discriminated outcomes:
unknown_tenant / owner / contact / customer. Mocks the asyncpg connection
the same way the rest of the backend tests do.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.chatbot.channels import whatsapp_resolver


class _FakeConn:
    def __init__(self) -> None:
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

    monkeypatch.setattr(whatsapp_resolver, "get_db", fake_get_db)
    return pool


@pytest.mark.asyncio
async def test_returns_unknown_tenant_when_no_business_matches(conn):
    conn.fetchrow.return_value = None

    result = await whatsapp_resolver.resolve_inbound_sender("phone-id-1", "wa-1")

    assert result.kind == "unknown_tenant"
    assert result.business_id is None
    assert result.contact_id is None
    assert result.contact_name is None
    assert result.contact_role is None


@pytest.mark.asyncio
async def test_returns_owner_when_phone_number_matches(conn):
    business_id = uuid4()
    conn.fetchrow.return_value = {
        "business_id": business_id,
        "owner_phone_number": "wa-owner",
        "contact_id": None,
        "contact_name": None,
        "contact_role": None,
    }

    result = await whatsapp_resolver.resolve_inbound_sender("phone-id-1", "wa-owner")

    assert result.kind == "owner"
    assert result.business_id == business_id
    assert result.contact_id is None


@pytest.mark.asyncio
async def test_returns_contact_when_contact_row_joined(conn):
    business_id = uuid4()
    contact_id = uuid4()
    conn.fetchrow.return_value = {
        "business_id": business_id,
        "owner_phone_number": "wa-owner",  # not the sender
        "contact_id": contact_id,
        "contact_name": "Acme Vendor",
        "contact_role": "vendor",
    }

    result = await whatsapp_resolver.resolve_inbound_sender("phone-id-1", "wa-vendor")

    assert result.kind == "contact"
    assert result.business_id == business_id
    assert result.contact_id == contact_id
    assert result.contact_name == "Acme Vendor"
    assert result.contact_role == "vendor"


@pytest.mark.asyncio
async def test_contact_match_wins_over_owner_match(conn):
    # Single-person business: the operator's wa_id is also registered as a
    # vendor contact. Resolver must classify as contact so the message drives
    # the outbound flow instead of being dropped as owner self-message.
    business_id = uuid4()
    contact_id = uuid4()
    conn.fetchrow.return_value = {
        "business_id": business_id,
        "owner_phone_number": "wa-owner",
        "contact_id": contact_id,
        "contact_name": "Self Vendor",
        "contact_role": "vendor",
    }

    result = await whatsapp_resolver.resolve_inbound_sender("phone-id-1", "wa-owner")

    assert result.kind == "contact"
    assert result.contact_id == contact_id


@pytest.mark.asyncio
async def test_returns_customer_when_no_contact_match_and_not_owner(conn):
    business_id = uuid4()
    conn.fetchrow.return_value = {
        "business_id": business_id,
        "owner_phone_number": "wa-owner",  # not the sender
        "contact_id": None,
        "contact_name": None,
        "contact_role": None,
    }

    result = await whatsapp_resolver.resolve_inbound_sender("phone-id-1", "wa-someone")

    assert result.kind == "customer"
    assert result.business_id == business_id
    assert result.contact_id is None
    assert result.contact_name is None
