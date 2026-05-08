"""Outbound timeout sweeper tests."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.chatbot import sweeper


def _row(*, customer_id=None, contact_name="Vendor X", task_key="tk-1"):
    return {
        "task_key": task_key,
        "business_id": uuid4(),
        "customer_id": customer_id or uuid4(),
        "contact_id": uuid4(),
        "contact_name": contact_name,
        "contact_role": "vendor",
    }


@pytest.mark.asyncio
async def test_sweep_once_notifies_each_timed_out_customer(monkeypatch):
    rows = [_row(task_key="tk-a"), _row(task_key="tk-b")]
    monkeypatch.setattr(
        sweeper.outbound_ledger,
        "sweep_timeouts",
        AsyncMock(return_value=rows),
    )
    notify = AsyncMock()
    monkeypatch.setattr(sweeper, "_notify_customer_of_timeout", notify)

    result = await sweeper.sweep_once()

    assert result == rows
    assert notify.await_count == 2


@pytest.mark.asyncio
async def test_sweep_once_isolates_per_row_failures(monkeypatch):
    """A failed customer notification on one row must not skip the rest."""
    rows = [_row(task_key="tk-a"), _row(task_key="tk-b")]
    monkeypatch.setattr(
        sweeper.outbound_ledger,
        "sweep_timeouts",
        AsyncMock(return_value=rows),
    )
    side_effects = [RuntimeError("inbox down"), None]
    notify = AsyncMock(side_effect=side_effects)
    monkeypatch.setattr(sweeper, "_notify_customer_of_timeout", notify)

    result = await sweeper.sweep_once()

    assert result == rows
    assert notify.await_count == 2


@pytest.mark.asyncio
async def test_sweep_once_no_timeouts_no_notifications(monkeypatch):
    monkeypatch.setattr(
        sweeper.outbound_ledger,
        "sweep_timeouts",
        AsyncMock(return_value=[]),
    )
    notify = AsyncMock()
    monkeypatch.setattr(sweeper, "_notify_customer_of_timeout", notify)

    result = await sweeper.sweep_once()

    assert result == []
    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_sweep_loop_runs_iteration_and_propagates_cancel(monkeypatch):
    sweep_once_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(sweeper, "sweep_once", sweep_once_mock)

    sleep_mock = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(sweeper.asyncio, "sleep", sleep_mock)

    with pytest.raises(asyncio.CancelledError):
        await sweeper.sweep_loop(interval_seconds=1)

    sweep_once_mock.assert_awaited_once()
    sleep_mock.assert_awaited_once_with(1)
