"""Tests for the outbound dispatch helper and agent hooks.

No live DB and no live model — we mock `outbound_ledger`, the outbound
agent's `run`, and the resolution router. Tests exercise the Batch 2
wiring: ledger insert + asyncio-task lifecycle, mark_completed validation,
after-tool hook fan-out, and before-model cancellation guard.
"""

from __future__ import annotations

import asyncio
from typing import Any
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from backend.chatbot.agents import outbound
from backend.chatbot.routers import outbound_resolution


@pytest.fixture
def patch_ledger(monkeypatch):
    fake = SimpleNamespace(
        insert_task=AsyncMock(return_value=None),
        mark_running=AsyncMock(return_value=True),
        mark_completed=AsyncMock(return_value=True),
        mark_failed=AsyncMock(return_value=True),
        get_state=AsyncMock(return_value="running"),
    )
    monkeypatch.setattr(outbound, "outbound_ledger", fake)
    return fake


@pytest.mark.asyncio
async def test_dispatch_inserts_ledger_row_and_returns_task_key(patch_ledger, monkeypatch):
    run_mock = AsyncMock(return_value=SimpleNamespace(output="ok"))
    monkeypatch.setattr(outbound.outbound_agent, "run", run_mock)

    business_id = uuid4()
    customer_id = uuid4()

    task_key = await outbound.dispatch(
        business_id=business_id,
        customer_id=customer_id,
        party="vendor-x",
        initiated_by="customer",
        dispatch_prompt="ask vendor for stock",
        business_name="Acme",
    )

    # task_key is a uuid4 hex string
    assert isinstance(task_key, str)
    assert len(task_key) == 32
    UUID(hex=task_key)

    patch_ledger.insert_task.assert_awaited_once()
    call_kwargs = patch_ledger.insert_task.await_args.kwargs
    assert call_kwargs["task_key"] == task_key
    assert call_kwargs["business_id"] == business_id
    assert call_kwargs["customer_id"] == customer_id
    assert call_kwargs["party"] == "vendor-x"
    assert call_kwargs["initiated_by"] == "customer"
    assert call_kwargs["dispatch_prompt"] == "ask vendor for stock"
    assert "timeout_at" in call_kwargs

    # Let the spawned background task drain.
    await asyncio.sleep(0)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_dispatch_spawns_task_that_marks_running_then_runs_agent(
    patch_ledger, monkeypatch
):
    order: list[str] = []

    async def _mark_running(task_key: str) -> bool:
        order.append("mark_running")
        return True

    async def _run(prompt: str, deps: outbound.OutboundDeps) -> Any:
        order.append("agent.run")
        return SimpleNamespace(output="done")

    patch_ledger.mark_running = AsyncMock(side_effect=_mark_running)
    monkeypatch.setattr(outbound.outbound_agent, "run", AsyncMock(side_effect=_run))

    await outbound.dispatch(
        business_id=uuid4(),
        customer_id=uuid4(),
        party="vendor",
        initiated_by="customer",
        dispatch_prompt="hi",
    )

    # Drain the background task.
    for _ in range(5):
        await asyncio.sleep(0)

    assert order == ["mark_running", "agent.run"]


@pytest.mark.asyncio
async def test_dispatch_marks_failed_on_agent_exception(patch_ledger, monkeypatch):
    async def _boom(prompt: str, deps: outbound.OutboundDeps) -> Any:
        raise RuntimeError("model exploded")

    monkeypatch.setattr(outbound.outbound_agent, "run", AsyncMock(side_effect=_boom))

    await outbound.dispatch(
        business_id=uuid4(),
        customer_id=uuid4(),
        party="vendor",
        initiated_by="customer",
        dispatch_prompt="hi",
    )

    for _ in range(5):
        await asyncio.sleep(0)

    patch_ledger.mark_failed.assert_awaited_once()
    kwargs = patch_ledger.mark_failed.await_args.kwargs
    assert kwargs["system_context"] == "model exploded"


@pytest.mark.asyncio
async def test_dispatch_does_not_mark_failed_on_cancellation(patch_ledger, monkeypatch):
    async def _cancel(prompt: str, deps: outbound.OutboundDeps) -> Any:
        raise outbound.OutboundCancelled(deps.task_key)

    monkeypatch.setattr(outbound.outbound_agent, "run", AsyncMock(side_effect=_cancel))

    await outbound.dispatch(
        business_id=uuid4(),
        customer_id=uuid4(),
        party="vendor",
        initiated_by="customer",
        dispatch_prompt="hi",
    )

    for _ in range(5):
        await asyncio.sleep(0)

    patch_ledger.mark_failed.assert_not_awaited()


def _make_ctx(task_key: str = "tk-1") -> Any:
    deps = outbound.OutboundDeps(
        task_key=task_key,
        business_id=uuid4(),
        customer_id=uuid4(),
        party="vendor",
        initiated_by="customer",
        dispatch_prompt="hi",
    )
    return SimpleNamespace(deps=deps)


@pytest.mark.asyncio
async def test_mark_completed_validates_at_least_one_context(patch_ledger):
    ctx = _make_ctx()
    with pytest.raises(ValueError):
        await outbound.mark_completed(ctx, None, None)
    with pytest.raises(ValueError):
        await outbound.mark_completed(ctx, "", "")


@pytest.mark.asyncio
async def test_mark_completed_writes_ledger_and_acknowledges(patch_ledger):
    ctx = _make_ctx(task_key="tk-42")
    result = await outbound.mark_completed(ctx, "hi customer", None)
    assert result == {"acknowledged": True}
    patch_ledger.mark_completed.assert_awaited_once_with("tk-42", "hi customer", None)


@pytest.mark.asyncio
async def test_after_tool_hook_calls_resolution_router(monkeypatch, patch_ledger):
    route_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(outbound_resolution, "route", route_mock)

    ctx = _make_ctx(task_key="tk-route")
    result = await outbound._on_mark_completed(
        ctx,
        call=None,
        tool_def=None,
        args={"customer_context": "x", "system_context": None},
        result={"acknowledged": True},
    )

    route_mock.assert_awaited_once_with("tk-route")
    assert result == {"acknowledged": True}


@pytest.mark.asyncio
async def test_cancellation_guard_aborts_when_state_is_cancelled(patch_ledger):
    patch_ledger.get_state = AsyncMock(return_value="cancelled")
    ctx = _make_ctx(task_key="tk-cancel")

    sentinel = object()
    with pytest.raises(outbound.OutboundCancelled):
        await outbound._cancellation_guard(ctx, sentinel)


@pytest.mark.asyncio
async def test_cancellation_guard_passthrough_when_running(patch_ledger):
    patch_ledger.get_state = AsyncMock(return_value="running")
    ctx = _make_ctx()

    sentinel = object()
    returned = await outbound._cancellation_guard(ctx, sentinel)
    assert returned is sentinel


def test_hooks_registered_on_agent():
    registry = outbound._hooks._registry
    assert "before_model_request" in registry
    assert "after_tool_execute" in registry
    after_entries = registry["after_tool_execute"]
    assert any("mark_completed" in (e.tools or ()) for e in after_entries)


@pytest.mark.asyncio
async def test_dispatch_rejects_at_max_depth(patch_ledger, monkeypatch):
    monkeypatch.setattr(
        outbound.outbound_agent, "run", AsyncMock(return_value=SimpleNamespace(output="ok"))
    )

    # parent_depth = max - 1 still permits one more dispatch (next_depth == max).
    task_key = await outbound.dispatch(
        business_id=uuid4(),
        customer_id=uuid4(),
        party="vendor",
        initiated_by="customer",
        dispatch_prompt="hi",
        parent_depth=outbound.OUTBOUND_MAX_DEPTH - 1,
    )
    assert isinstance(task_key, str)
    for _ in range(5):
        await asyncio.sleep(0)

    # parent_depth = max means next_depth exceeds the limit.
    with pytest.raises(ValueError):
        await outbound.dispatch(
            business_id=uuid4(),
            customer_id=uuid4(),
            party="vendor",
            initiated_by="customer",
            dispatch_prompt="hi",
            parent_depth=outbound.OUTBOUND_MAX_DEPTH,
        )


@pytest.mark.asyncio
async def test_dispatch_passes_current_depth_to_deps(patch_ledger, monkeypatch):
    captured: dict[str, Any] = {}

    async def _capture(prompt: str, deps: outbound.OutboundDeps) -> Any:
        captured["deps"] = deps
        return SimpleNamespace(output="ok")

    monkeypatch.setattr(outbound.outbound_agent, "run", AsyncMock(side_effect=_capture))

    parent_depth = 1
    await outbound.dispatch(
        business_id=uuid4(),
        customer_id=uuid4(),
        party="vendor",
        initiated_by="customer",
        dispatch_prompt="hi",
        parent_depth=parent_depth,
    )

    for _ in range(5):
        await asyncio.sleep(0)

    assert captured["deps"].current_depth == parent_depth + 1
