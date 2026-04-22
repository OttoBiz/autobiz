"""Tests for the outbound resolution router.

Mocks the ledger, channel registry, channel handler, inbox lock, and the
coordinator agent. No real DB or Redis.
"""

from __future__ import annotations

import os

# Match the pattern in test_inbox.py: DEBUG=true so cache.py picks the
# non-cluster Redis client. Tests don't actually touch Redis (lock is mocked).
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "")

import logging  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from types import ModuleType, SimpleNamespace  # noqa: E402
from typing import ClassVar  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402

from backend.chatbot.channels.base import (  # noqa: E402
    Channel,
    ChannelIdentity,
    InboundMessage,
    WindowPolicy,
)
from backend.chatbot.routers import outbound_resolution  # noqa: E402
from backend.db.outbound_ledger import OutboundTaskRow  # noqa: E402


class _FakeChannel(Channel):
    name: ClassVar[str] = "fake"

    def parse_inbound(self, raw: dict) -> InboundMessage:  # pragma: no cover
        raise NotImplementedError

    async def send(self, identity: ChannelIdentity, text: str) -> None:  # pragma: no cover
        raise NotImplementedError

    async def send_template(  # pragma: no cover
        self, identity: ChannelIdentity, template: str, vars: dict
    ) -> None:
        raise NotImplementedError

    def window_policy(self) -> WindowPolicy:
        return WindowPolicy(
            has_window=True, window_hours=24, out_of_window_behavior="template"
        )


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
        party="vendor-x",
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
def patch_get_for_customer(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(outbound_resolution.registry, "get_for_customer", mock)
    return mock


@pytest.fixture
def patch_handle_resolution(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(outbound_resolution, "handle_resolution", mock)
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
    patch_get_by_key, patch_get_for_customer, patch_handle_resolution, patch_lock
):
    patch_get_by_key.return_value = None

    await outbound_resolution.route("tk-missing")

    patch_get_for_customer.assert_not_awaited()
    patch_handle_resolution.assert_not_awaited()
    patch_lock.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_route_returns_early_when_state_not_terminal(
    patch_get_by_key, patch_get_for_customer, patch_handle_resolution, patch_lock
):
    patch_get_by_key.return_value = _make_task(
        state="running", customer_context="hi", system_context="back-office"
    )

    await outbound_resolution.route("tk-running")

    patch_get_for_customer.assert_not_awaited()
    patch_handle_resolution.assert_not_awaited()
    patch_lock.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_customer_context_only_calls_handler_not_coordinator(
    patch_get_by_key,
    patch_get_for_customer,
    patch_handle_resolution,
    patch_lock,
    patch_coordinator,
):
    task = _make_task(customer_context="order shipped")
    patch_get_by_key.return_value = task
    channel = _FakeChannel()
    patch_get_for_customer.return_value = channel

    await outbound_resolution.route(task.task_key)

    patch_get_for_customer.assert_awaited_once_with(
        str(task.business_id), str(task.customer_id)
    )
    patch_handle_resolution.assert_awaited_once_with(task, channel)
    patch_lock.acquire.assert_not_called()
    patch_coordinator.coordinator_agent.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_system_context_only_runs_coordinator_not_handler(
    patch_get_by_key,
    patch_get_for_customer,
    patch_handle_resolution,
    patch_lock,
    patch_coordinator,
):
    task = _make_task(system_context="restock SKU-1")
    patch_get_by_key.return_value = task

    await outbound_resolution.route(task.task_key)

    patch_get_for_customer.assert_not_awaited()
    patch_handle_resolution.assert_not_awaited()
    patch_lock.acquire.assert_called_once()
    patch_lock.release.assert_called_once()
    patch_coordinator.coordinator_agent.run.assert_awaited_once()
    call = patch_coordinator.coordinator_agent.run.await_args
    deps = call.kwargs["deps"]
    assert deps.business_id == task.business_id
    assert deps.customer_id == task.customer_id
    assert deps.triggering_task_key == task.task_key
    prompt = call.args[0]
    assert "vendor-x" in prompt
    assert "restock SKU-1" in prompt


@pytest.mark.asyncio
async def test_both_contexts_run_handler_and_coordinator(
    patch_get_by_key,
    patch_get_for_customer,
    patch_handle_resolution,
    patch_lock,
    patch_coordinator,
):
    task = _make_task(
        customer_context="we are on it", system_context="open follow-up"
    )
    patch_get_by_key.return_value = task
    channel = _FakeChannel()
    patch_get_for_customer.return_value = channel

    await outbound_resolution.route(task.task_key)

    patch_handle_resolution.assert_awaited_once_with(task, channel)
    patch_coordinator.coordinator_agent.run.assert_awaited_once()
    patch_lock.release.assert_called_once()


@pytest.mark.asyncio
async def test_coordinator_import_failure_logs_and_continues(
    patch_get_by_key,
    patch_get_for_customer,
    patch_handle_resolution,
    patch_lock,
    monkeypatch,
    caplog,
):
    # Force the lazy import to fail by inserting a stub module that raises
    # on attribute access — actually, simpler: shadow with None so import-from
    # fails. We use a module stub missing the required names.
    broken = ModuleType("backend.chatbot.agents.coordinator")
    monkeypatch.setitem(sys.modules, "backend.chatbot.agents.coordinator", broken)

    task = _make_task(system_context="something")
    patch_get_by_key.return_value = task

    with caplog.at_level(logging.WARNING, logger=outbound_resolution.logger.name):
        await outbound_resolution.route(task.task_key)

    # Lock acquired and released even though coordinator was unavailable.
    patch_lock.acquire.assert_called_once()
    patch_lock.release.assert_called_once()
    assert any("coordinator not available" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_lock_contention_skips_coordinator_and_no_release(
    patch_get_by_key,
    patch_get_for_customer,
    patch_handle_resolution,
    patch_lock,
    patch_coordinator,
    caplog,
):
    patch_lock.acquire.return_value = False
    task = _make_task(system_context="contended")
    patch_get_by_key.return_value = task

    with caplog.at_level(logging.INFO, logger=outbound_resolution.logger.name):
        await outbound_resolution.route(task.task_key)

    patch_coordinator.coordinator_agent.run.assert_not_awaited()
    patch_lock.release.assert_not_called()
    assert any("lock contention" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_no_channel_for_customer_skips_handler_and_warns(
    patch_get_by_key,
    patch_get_for_customer,
    patch_handle_resolution,
    patch_lock,
    caplog,
):
    task = _make_task(customer_context="hi")
    patch_get_by_key.return_value = task
    patch_get_for_customer.return_value = None

    with caplog.at_level(logging.WARNING, logger=outbound_resolution.logger.name):
        await outbound_resolution.route(task.task_key)

    patch_handle_resolution.assert_not_awaited()
    assert any("no channel for resolution" in r.getMessage() for r in caplog.records)
