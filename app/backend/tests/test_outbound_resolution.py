"""Tests for the outbound resolution router.

The router translates a resolved ledger row into queued inbox items and wakes
central to drain. Mocks the ledger, the coordinator agent, the inbox lock,
`inbox.enqueue`, and `orchestrator.wake_central` so we can assert the wiring
without a real DB, Redis, or LLM.
"""

from __future__ import annotations

import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "")

import logging  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from types import ModuleType, SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402

from backend.chatbot.routers import outbound_resolution  # noqa: E402
from backend.db.outbound_ledger import OutboundTaskRow  # noqa: E402


def _make_task(
    *,
    state: str = "succeeded",
    customer_context: str | None = None,
    system_context: str | None = None,
) -> OutboundTaskRow:
    now = datetime.now(timezone.utc)
    return OutboundTaskRow(
        task_key="tk-1",
        business_id=uuid4(),
        customer_id=uuid4(),
        contact_id=uuid4(),
        contact_name="Vendor X",
        contact_role="vendor",
        initiated_by="customer",
        dispatch_prompt="ask vendor",
        state=state,  # type: ignore[arg-type]
        customer_context=customer_context,
        system_context=system_context,
        dispatched_at=now,
        resolved_at=now,
        timeout_at=now + timedelta(minutes=5),
    )


@pytest.fixture
def patch_get_by_key(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(outbound_resolution.outbound_ledger, "get_by_key", mock)
    return mock


@pytest.fixture
def patch_enqueue(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(outbound_resolution.inbox, "enqueue", mock)
    return mock


@pytest.fixture
def patch_wake(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(outbound_resolution.orchestrator, "wake_central", mock)
    return mock


@pytest.fixture
def patch_lock(monkeypatch):
    acquire = MagicMock(return_value=True)
    release = MagicMock(return_value=True)
    monkeypatch.setattr(outbound_resolution.inbox, "acquire_lock", acquire)
    monkeypatch.setattr(outbound_resolution.inbox, "release_lock", release)
    return SimpleNamespace(acquire=acquire, release=release)


@pytest.fixture
def patch_coordinator(monkeypatch):
    """Inject a fake `backend.chatbot.agents.coordinator` module so the lazy
    import inside `_run_coordinator` resolves without loading the real one."""
    fake = ModuleType("backend.chatbot.agents.coordinator")

    class CoordinatorDeps:
        def __init__(self, business_id, customer_id, triggering_task_key):
            self.business_id = business_id
            self.customer_id = customer_id
            self.triggering_task_key = triggering_task_key

    coordinator_agent = SimpleNamespace(run=AsyncMock(return_value=None))
    fake.CoordinatorDeps = CoordinatorDeps  # type: ignore[attr-defined]
    fake.coordinator_agent = coordinator_agent  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "backend.chatbot.agents.coordinator", fake)
    return fake


@pytest.mark.asyncio
async def test_route_returns_early_when_task_missing(
    patch_get_by_key, patch_enqueue, patch_wake, patch_lock
):
    patch_get_by_key.return_value = None

    await outbound_resolution.route("tk-missing")

    patch_enqueue.assert_not_called()
    patch_wake.assert_not_awaited()
    patch_lock.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_route_returns_early_when_state_not_terminal(
    patch_get_by_key, patch_enqueue, patch_wake, patch_lock
):
    patch_get_by_key.return_value = _make_task(
        state="running", customer_context="hi", system_context="back-office"
    )

    await outbound_resolution.route("tk-running")

    patch_enqueue.assert_not_called()
    patch_wake.assert_not_awaited()
    patch_lock.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_customer_context_is_enqueued_then_central_is_woken(
    patch_get_by_key, patch_enqueue, patch_wake, patch_lock, patch_coordinator
):
    task = _make_task(customer_context="order shipped")
    patch_get_by_key.return_value = task

    await outbound_resolution.route(task.task_key)

    patch_enqueue.assert_called_once()
    biz, cust, item = patch_enqueue.call_args.args
    assert biz == str(task.business_id)
    assert cust == str(task.customer_id)
    assert item["type"] == "system_event"
    assert item["payload"]["summary"] == "order shipped"
    assert item["payload"]["source"] == "outbound_reply"
    assert item["payload"]["contact_name"] == task.contact_name
    assert item["payload"]["contact_role"] == task.contact_role
    assert item["payload"]["task_key"] == task.task_key

    patch_wake.assert_awaited_once_with(str(task.business_id), str(task.customer_id))
    # Customer_context-only tasks don't touch the coordinator at all.
    patch_coordinator.coordinator_agent.run.assert_not_awaited()
    patch_lock.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_system_context_only_runs_coordinator_and_still_wakes_central(
    patch_get_by_key, patch_enqueue, patch_wake, patch_lock, patch_coordinator
):
    # This is the regression this whole change is about: the coordinator may
    # call surface_to_customer, which just enqueues. If we never call
    # wake_central here, that summary would sit in the inbox until the next
    # customer message — delivery lag / silent drop on idle customers.
    task = _make_task(system_context="restock SKU-1")
    patch_get_by_key.return_value = task

    await outbound_resolution.route(task.task_key)

    patch_enqueue.assert_not_called()  # no customer_context on this task
    patch_lock.acquire.assert_called_once()
    patch_lock.release.assert_called_once()
    patch_coordinator.coordinator_agent.run.assert_awaited_once()
    call = patch_coordinator.coordinator_agent.run.await_args
    deps = call.kwargs["deps"]
    assert deps.business_id == task.business_id
    assert deps.customer_id == task.customer_id
    assert deps.triggering_task_key == task.task_key
    prompt = call.args[0]
    assert "Vendor X" in prompt
    assert "restock SKU-1" in prompt
    # customer_context absent → prompt should not include the
    # "already queued" preamble (the guidance line about avoiding
    # duplicates with customer_context still appears, which is fine).
    assert "already queued for the customer" not in prompt

    # The wake happens regardless of whether the coordinator surfaced anything
    # — `wake_central` no-ops on an empty queue.
    patch_wake.assert_awaited_once_with(str(task.business_id), str(task.customer_id))


@pytest.mark.asyncio
async def test_both_contexts_run_coordinator_enqueue_and_wake_once(
    patch_get_by_key, patch_enqueue, patch_wake, patch_lock, patch_coordinator
):
    task = _make_task(
        customer_context="we are on it", system_context="open follow-up"
    )
    patch_get_by_key.return_value = task

    await outbound_resolution.route(task.task_key)

    # Coordinator ran first.
    patch_lock.acquire.assert_called_once()
    patch_lock.release.assert_called_once()
    patch_coordinator.coordinator_agent.run.assert_awaited_once()
    prompt = patch_coordinator.coordinator_agent.run.await_args.args[0]
    # Prompt now includes customer_context so the coordinator doesn't
    # duplicate it via surface_to_customer.
    assert "we are on it" in prompt
    assert "open follow-up" in prompt

    # Then the customer-facing summary was enqueued.
    patch_enqueue.assert_called_once()
    _biz, _cust, item = patch_enqueue.call_args.args
    assert item["payload"]["summary"] == "we are on it"

    # And central was woken exactly once for the combined drain.
    patch_wake.assert_awaited_once()


@pytest.mark.asyncio
async def test_coordinator_import_failure_logs_and_continues(
    patch_get_by_key, patch_enqueue, patch_wake, patch_lock, monkeypatch, caplog
):
    # Shadow the coordinator module with a stub missing the required names so
    # the `from ... import` inside `_run_coordinator` raises ImportError.
    broken = ModuleType("backend.chatbot.agents.coordinator")
    monkeypatch.setitem(sys.modules, "backend.chatbot.agents.coordinator", broken)

    task = _make_task(system_context="something")
    patch_get_by_key.return_value = task

    with caplog.at_level(logging.WARNING, logger=outbound_resolution.logger.name):
        await outbound_resolution.route(task.task_key)

    patch_lock.acquire.assert_called_once()
    patch_lock.release.assert_called_once()
    assert any("coordinator not available" in r.getMessage() for r in caplog.records)
    # Even with a broken coordinator import we still wake central so any
    # pre-existing queued items (from a concurrent handle_inbound, say) drain.
    patch_wake.assert_awaited_once()


@pytest.mark.asyncio
async def test_coordinator_lock_contention_skips_run_but_still_delivers(
    patch_get_by_key,
    patch_enqueue,
    patch_wake,
    patch_lock,
    patch_coordinator,
    caplog,
):
    # Coordinator can't acquire the lock, but a concurrent customer_context
    # should still reach the customer via wake_central.
    patch_lock.acquire.return_value = False
    task = _make_task(
        customer_context="here's the quote", system_context="back-office note"
    )
    patch_get_by_key.return_value = task

    with caplog.at_level(logging.INFO, logger=outbound_resolution.logger.name):
        await outbound_resolution.route(task.task_key)

    patch_coordinator.coordinator_agent.run.assert_not_awaited()
    patch_lock.release.assert_not_called()
    patch_enqueue.assert_called_once()
    patch_wake.assert_awaited_once()
    assert any("lock contention" in r.getMessage() for r in caplog.records)
