"""Tests for central agent guardrails and tools.

No live model — we mock subagent `.run` and ledger/inbox accessors. Covers
the subagent timeout fallback and the get_outbound_status pull-model tool.
"""

from __future__ import annotations

import os

# central.py now imports `inbox`, which transitively loads cache.py — and
# cache.py picks cluster vs single-node Redis at import time off DEBUG. Set
# DEBUG=true before importing anything from backend.
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "")

import asyncio  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402

from backend.chatbot.agents import central  # noqa: E402
from backend.chatbot.agents.deps import AgentDeps  # noqa: E402
from backend.db.outbound_ledger import OutboundTaskRow  # noqa: E402


def _row(
    *,
    party: str = "vendor-x",
    state: str = "succeeded",
    customer_context: str | None = None,
    dispatch_prompt: str = "ask vendor",
    resolved_at: datetime | None = None,
) -> OutboundTaskRow:
    now = datetime.now(timezone.utc)
    return OutboundTaskRow(
        task_key=f"tk-{uuid4().hex[:6]}",
        business_id=uuid4(),
        customer_id=uuid4(),
        party=party,
        initiated_by="customer",
        dispatch_prompt=dispatch_prompt,
        state=state,  # type: ignore[arg-type]
        customer_context=customer_context,
        system_context=None,
        dispatched_at=now,
        resolved_at=resolved_at if resolved_at is not None else now,
        timeout_at=now + timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_handle_subagent_timeout(monkeypatch):
    # Tiny override keeps the test fast; the wrapper still exercises wait_for.
    monkeypatch.setattr(central, "SUBAGENT_TIMEOUT_SECONDS", 0.05)

    never_fires = asyncio.Event()

    class _StubAgent:
        async def run(self, prompt, deps):
            await never_fires.wait()
            return None  # pragma: no cover -- never reached

    import backend.chatbot.agents.product as product_mod

    monkeypatch.setattr(product_mod, "product_agent", _StubAgent())

    deps = AgentDeps(customer_id=uuid4(), business_id=uuid4())
    started = time.monotonic()
    result = await central._handle_product(deps, "anything")
    elapsed = time.monotonic() - started

    assert result == {"error": "subagent_timeout", "subagent": "product"}
    # Generous upper bound — guards against the wrapper accidentally hanging.
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_fetch_outbound_status_returns_pending_and_resolved(monkeypatch):
    biz, cust = uuid4(), uuid4()
    pending_row = _row(party="vendor-a", dispatch_prompt="confirm stock", state="running")
    resolved_at = datetime.now(timezone.utc)
    resolved_row = _row(
        party="vendor-b",
        customer_context="shipped today",
        resolved_at=resolved_at,
    )

    monkeypatch.setattr(central.inbox, "get_cursor", MagicMock(return_value=None))
    set_cursor = MagicMock()
    monkeypatch.setattr(central.inbox, "set_cursor", set_cursor)
    monkeypatch.setattr(
        central.outbound_ledger,
        "get_pending_for_customer",
        AsyncMock(return_value=[pending_row]),
    )
    monkeypatch.setattr(
        central.outbound_ledger,
        "get_resolved_since",
        AsyncMock(return_value=[resolved_row]),
    )

    result = await central._fetch_outbound_status(biz, cust)

    assert result == {
        "pending": [{"party": "vendor-a", "request": "confirm stock"}],
        "resolved": [{"party": "vendor-b", "outcome": "shipped today"}],
    }
    # Cursor advanced to the latest resolved_at.
    set_cursor.assert_called_once_with(str(biz), str(cust), resolved_at)


@pytest.mark.asyncio
async def test_fetch_outbound_status_no_resolved_leaves_cursor_alone(monkeypatch):
    monkeypatch.setattr(central.inbox, "get_cursor", MagicMock(return_value=None))
    set_cursor = MagicMock()
    monkeypatch.setattr(central.inbox, "set_cursor", set_cursor)
    monkeypatch.setattr(
        central.outbound_ledger,
        "get_pending_for_customer",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        central.outbound_ledger,
        "get_resolved_since",
        AsyncMock(return_value=[]),
    )

    result = await central._fetch_outbound_status(uuid4(), uuid4())

    assert result == {"pending": [], "resolved": []}
    set_cursor.assert_not_called()
