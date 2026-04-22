"""Tests for the coordinator agent's tool surface.

No LLM, no live DB, no live Redis. We mock `db_utils`, `outbound.dispatch`,
and `inbox.enqueue` and invoke the tool implementations directly.
"""

from __future__ import annotations

import os

# Match the pattern in test_inbox.py: DEBUG=true so cache.py picks the
# non-cluster Redis client, which we then swap for fakeredis below.
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "")

import logging  # noqa: E402
from decimal import Decimal  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402
from uuid import uuid4  # noqa: E402

import fakeredis  # noqa: E402
import pytest  # noqa: E402

from backend.chatbot.agents import coordinator  # noqa: E402
from backend.db import cache_utils  # noqa: E402


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch):
    monkeypatch.setattr(
        cache_utils.redis_conn, "_client", fakeredis.FakeRedis(decode_responses=True)
    )


def _make_ctx(
    *,
    current_depth: int = 0,
    max_depth: int = 3,
    triggering_task_key: str = "tk-trigger",
) -> Any:
    deps = coordinator.CoordinatorDeps(
        business_id=uuid4(),
        customer_id=uuid4(),
        triggering_task_key=triggering_task_key,
        max_depth=max_depth,
        current_depth=current_depth,
    )
    return SimpleNamespace(deps=deps)


# ---------- update_inventory ----------


@pytest.mark.asyncio
async def test_update_inventory_adjusts_stock_by_delta(monkeypatch):
    ctx = _make_ctx()
    product_id = str(uuid4())

    get_products = AsyncMock(
        return_value=[{"id": product_id, "sku": "SKU-1", "stock_quantity": 7}]
    )
    update_stock = AsyncMock(
        return_value={"id": product_id, "stock_quantity": 10}
    )
    monkeypatch.setattr(coordinator.db_utils, "get_products", get_products)
    monkeypatch.setattr(coordinator.db_utils, "update_product_stock", update_stock)

    result = await coordinator.update_inventory(ctx, sku="SKU-1", delta=3)

    assert result == {"ok": True, "sku": "SKU-1", "new_qty": 10}
    get_products.assert_awaited_once()
    update_stock.assert_awaited_once_with(product_id, 10)


@pytest.mark.asyncio
async def test_update_inventory_returns_not_found(monkeypatch):
    ctx = _make_ctx()
    monkeypatch.setattr(
        coordinator.db_utils, "get_products", AsyncMock(return_value=[])
    )
    update_stock = AsyncMock()
    monkeypatch.setattr(coordinator.db_utils, "update_product_stock", update_stock)

    result = await coordinator.update_inventory(ctx, sku="SKU-MISSING", delta=1)

    assert result["ok"] is False
    assert "not found" in result["reason"]
    update_stock.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_inventory_accepts_negative_delta(monkeypatch):
    ctx = _make_ctx()
    product_id = str(uuid4())
    monkeypatch.setattr(
        coordinator.db_utils,
        "get_products",
        AsyncMock(return_value=[{"id": product_id, "sku": "SKU-1", "stock_quantity": 5}]),
    )
    update_stock = AsyncMock(return_value={"id": product_id, "stock_quantity": 3})
    monkeypatch.setattr(coordinator.db_utils, "update_product_stock", update_stock)

    result = await coordinator.update_inventory(ctx, sku="SKU-1", delta=-2)

    update_stock.assert_awaited_once_with(product_id, 3)
    assert result == {"ok": True, "sku": "SKU-1", "new_qty": 3}


# ---------- update_price ----------


@pytest.mark.asyncio
async def test_update_price_sets_new_price(monkeypatch):
    ctx = _make_ctx()
    product_id = str(uuid4())
    monkeypatch.setattr(
        coordinator.db_utils,
        "get_products",
        AsyncMock(return_value=[{"id": product_id, "sku": "SKU-9"}]),
    )
    update_price = AsyncMock(
        return_value={"id": product_id, "sku": "SKU-9", "price": Decimal("19.99")}
    )
    monkeypatch.setattr(coordinator.db_utils, "update_product_price", update_price)

    result = await coordinator.update_price(ctx, sku="SKU-9", new_price=Decimal("19.99"))

    update_price.assert_awaited_once_with(product_id, Decimal("19.99"))
    assert result == {"ok": True, "sku": "SKU-9", "new_price": "19.99"}


@pytest.mark.asyncio
async def test_update_price_returns_not_found(monkeypatch):
    ctx = _make_ctx()
    monkeypatch.setattr(
        coordinator.db_utils, "get_products", AsyncMock(return_value=[])
    )
    update_price = AsyncMock()
    monkeypatch.setattr(coordinator.db_utils, "update_product_price", update_price)

    result = await coordinator.update_price(ctx, sku="NOPE", new_price=Decimal("1.00"))

    assert result["ok"] is False
    update_price.assert_not_awaited()


# ---------- update_vendor_contact ----------


@pytest.mark.asyncio
async def test_update_vendor_contact_filters_and_forwards_allowed_fields(monkeypatch):
    ctx = _make_ctx()
    vendor_id = str(uuid4())
    update_vendor = AsyncMock(return_value=True)
    monkeypatch.setattr(coordinator.db_utils, "update_vendor", update_vendor)

    result = await coordinator.update_vendor_contact(
        ctx,
        vendor_id=vendor_id,
        fields={"name": "Acme", "phone": "555", "email": "a@b.co", "notes": "ignored"},
    )

    assert result["ok"] is True
    assert set(result["updated_fields"]) == {"name", "phone", "email"}
    update_vendor.assert_awaited_once()
    args, kwargs = update_vendor.await_args
    assert args[0] == coordinator.UUID(vendor_id)
    assert kwargs == {"name": "Acme", "phone": "555", "email": "a@b.co"}


@pytest.mark.asyncio
async def test_update_vendor_contact_no_allowed_fields(monkeypatch):
    ctx = _make_ctx()
    update_vendor = AsyncMock()
    monkeypatch.setattr(coordinator.db_utils, "update_vendor", update_vendor)

    result = await coordinator.update_vendor_contact(
        ctx, vendor_id=str(uuid4()), fields={"notes": "irrelevant"}
    )

    assert result == {"ok": False, "reason": "no updatable fields"}
    update_vendor.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_vendor_contact_vendor_not_found(monkeypatch):
    ctx = _make_ctx()
    monkeypatch.setattr(
        coordinator.db_utils, "update_vendor", AsyncMock(return_value=False)
    )

    result = await coordinator.update_vendor_contact(
        ctx, vendor_id=str(uuid4()), fields={"name": "X"}
    )

    assert result == {"ok": False, "reason": "vendor not found"}


# ---------- record_note ----------


@pytest.mark.asyncio
async def test_record_note_logs_and_returns_ok(caplog):
    ctx = _make_ctx(triggering_task_key="tk-42")

    with caplog.at_level(logging.INFO, logger=coordinator.logger.name):
        result = await coordinator.record_note(
            ctx, subject="restock", content="vendor confirmed 50 units"
        )

    assert result == {"ok": True, "logged": True}
    assert any("coordinator_note" in r.getMessage() for r in caplog.records)
    assert any("tk-42" in r.getMessage() for r in caplog.records)
    assert any("restock" in r.getMessage() for r in caplog.records)


# ---------- dispatch_outbound ----------


@pytest.mark.asyncio
async def test_dispatch_outbound_calls_dispatch_with_system_initiated_by(monkeypatch):
    ctx = _make_ctx(current_depth=0, max_depth=3)
    dispatch = AsyncMock(return_value="new-task-key")
    monkeypatch.setattr(coordinator.outbound, "dispatch", dispatch)

    task_key = await coordinator.dispatch_outbound(
        ctx, party="backup-vendor", prompt="can you fulfill?", timeout_seconds=1800
    )

    assert task_key == "new-task-key"
    dispatch.assert_awaited_once()
    kwargs = dispatch.await_args.kwargs
    assert kwargs["business_id"] == ctx.deps.business_id
    assert kwargs["customer_id"] == ctx.deps.customer_id
    assert kwargs["party"] == "backup-vendor"
    assert kwargs["initiated_by"] == "system"
    assert kwargs["dispatch_prompt"] == "can you fulfill?"
    assert kwargs["timeout_seconds"] == 1800
    assert kwargs["parent_depth"] == 0


@pytest.mark.asyncio
async def test_dispatch_outbound_forwards_current_depth_as_parent_depth(monkeypatch):
    ctx = _make_ctx(current_depth=2, max_depth=3)
    dispatch = AsyncMock(return_value="tk")
    monkeypatch.setattr(coordinator.outbound, "dispatch", dispatch)

    # Depth enforcement lives in `outbound.dispatch`; the coordinator just
    # propagates its own `current_depth` as the dispatch's `parent_depth`.
    await coordinator.dispatch_outbound(ctx, party="p", prompt="x")

    assert dispatch.await_args.kwargs["parent_depth"] == 2


# ---------- surface_to_customer ----------


@pytest.mark.asyncio
async def test_surface_to_customer_enqueues_system_event(monkeypatch):
    ctx = _make_ctx(triggering_task_key="tk-source")
    enqueue = MagicMock()
    monkeypatch.setattr(coordinator.inbox, "enqueue", enqueue)

    result = await coordinator.surface_to_customer(ctx, summary="your order shipped")

    assert result == {"ok": True}
    enqueue.assert_called_once()
    biz_arg, cust_arg, item = enqueue.call_args.args
    assert biz_arg == str(ctx.deps.business_id)
    assert cust_arg == str(ctx.deps.customer_id)
    assert item["type"] == "system_event"
    assert item["payload"] == {
        "summary": "your order shipped",
        "source_task": "tk-source",
    }
    assert "enqueued_at" in item and isinstance(item["enqueued_at"], str)


# ---------- escalate_to_operator ----------


@pytest.mark.asyncio
async def test_escalate_to_operator_logs_structured_fields(caplog):
    ctx = _make_ctx(triggering_task_key="tk-esc")

    with caplog.at_level(logging.WARNING, logger=coordinator.logger.name):
        result = await coordinator.escalate_to_operator(
            ctx,
            reason="unsure about refund policy",
            options=["refund", "store_credit"],
        )

    assert result == {"escalated": True}
    messages = [r.getMessage() for r in caplog.records]
    assert any("coordinator_escalation" in m for m in messages)
    assert any("tk-esc" in m for m in messages)
    assert any("unsure about refund policy" in m for m in messages)
    assert any("refund" in m and "store_credit" in m for m in messages)


@pytest.mark.asyncio
async def test_escalate_to_operator_handles_no_options(caplog):
    ctx = _make_ctx()

    with caplog.at_level(logging.WARNING, logger=coordinator.logger.name):
        result = await coordinator.escalate_to_operator(ctx, reason="novel situation")

    assert result == {"escalated": True}
    assert any("novel situation" in r.getMessage() for r in caplog.records)
