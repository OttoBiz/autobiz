"""Outbound timeout sweeper tests."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.chatbot import sweeper


@pytest.mark.asyncio
async def test_sweep_once_alerts_per_timed_out_key(monkeypatch):
    monkeypatch.setattr(
        sweeper.outbound_ledger,
        "sweep_timeouts",
        AsyncMock(return_value=["k1", "k2"]),
    )
    alert = AsyncMock()
    monkeypatch.setattr(sweeper, "alert_operator", alert)

    result = await sweeper.sweep_once()

    assert result == ["k1", "k2"]
    assert alert.await_count == 2
    assert alert.await_args_list[0].args == ("k1",)
    assert alert.await_args_list[0].kwargs == {"reason": "timeout"}
    assert alert.await_args_list[1].args == ("k2",)
    assert alert.await_args_list[1].kwargs == {"reason": "timeout"}


@pytest.mark.asyncio
async def test_sweep_once_no_timeouts_no_alerts(monkeypatch):
    monkeypatch.setattr(
        sweeper.outbound_ledger,
        "sweep_timeouts",
        AsyncMock(return_value=[]),
    )
    alert = AsyncMock()
    monkeypatch.setattr(sweeper, "alert_operator", alert)

    result = await sweeper.sweep_once()

    assert result == []
    alert.assert_not_awaited()


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
