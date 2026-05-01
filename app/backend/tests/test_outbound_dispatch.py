"""Tests for the outbound dispatch helper and agent hooks.

No live DB and no live model — we mock `outbound_ledger`, the outbound
agent's `run`, and the resolution router. Tests exercise the Batch 2
wiring: ledger insert + asyncio-task lifecycle, mark_completed validation,
after-tool hook fan-out, and before-model cancellation guard.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from backend.chatbot.agents import outbound
from backend.chatbot.routers import outbound_resolution
from backend.db.contacts import Contact


def _make_contact(business_id: UUID | None = None) -> Contact:
    now = datetime.now(timezone.utc)
    return Contact(
        id=uuid4(),
        business_id=business_id or uuid4(),
        name="Vendor X",
        role="vendor",
        channel="whatsapp",
        channel_user_id="vendor-wa-1",
        channel_business_id=None,
        notes=None,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture(autouse=True)
def patch_contacts(monkeypatch):
    """Default: any contact lookup returns a fresh contact with a matching biz."""
    fake = SimpleNamespace(get_by_id=AsyncMock(side_effect=lambda cid: _make_contact()))
    monkeypatch.setattr(outbound, "contacts", fake)
    return fake


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


@pytest.fixture(autouse=True)
def patch_transport(monkeypatch):
    """Stub the dispatch-entry transport resolution so tests don't hit Redis/DB.

    `outbound._send_to_party` now resolves the contact's channel identity via
    `_contact_identity`. Default it to None so the send path returns a status
    string rather than touching the registry. Tests that exercise message
    delivery override this with their own AsyncMock.
    """
    monkeypatch.setattr(
        outbound, "_contact_identity", AsyncMock(return_value=None)
    )


@pytest.fixture(autouse=True)
def patch_chat_storage(monkeypatch):
    """No real Redis writes during dispatch tests.

    dispatch._run now persists the opening exchange via chat_storage so the
    continuation helper has prior message_history to thread back in. Patch
    those calls — the real round-trip is exercised in test_chat_storage.
    """
    fake = SimpleNamespace(
        load_outbound_history=AsyncMock(return_value=[]),
        append_outbound_history=AsyncMock(),
    )
    monkeypatch.setattr(outbound, "chat_storage", fake)
    return fake


@pytest.mark.asyncio
async def test_dispatch_inserts_ledger_row_and_returns_task_key(
    patch_ledger, patch_contacts, monkeypatch
):
    run_mock = AsyncMock(return_value=SimpleNamespace(output="ok"))
    monkeypatch.setattr(outbound.outbound_agent, "run", run_mock)

    business_id = uuid4()
    customer_id = uuid4()
    contact = _make_contact(business_id=business_id)
    patch_contacts.get_by_id = AsyncMock(return_value=contact)

    task_key = await outbound.dispatch(
        business_id=business_id,
        customer_id=customer_id,
        contact_id=contact.id,
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
    assert call_kwargs["contact_id"] == contact.id
    assert call_kwargs["contact_name"] == contact.name
    assert call_kwargs["contact_role"] == contact.role
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
        contact_id=uuid4(),
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
        contact_id=uuid4(),
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
        contact_id=uuid4(),
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
        contact_id=uuid4(),
        contact_name="Vendor X",
        contact_role="vendor",
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
        contact_id=uuid4(),
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
            contact_id=uuid4(),
            initiated_by="customer",
            dispatch_prompt="hi",
            parent_depth=outbound.OUTBOUND_MAX_DEPTH,
        )


def _make_task_row(task_key: str = "tk-1", state: str = "running"):
    from datetime import datetime, timedelta, timezone

    from backend.db.outbound_ledger import OutboundTaskRow

    now = datetime.now(timezone.utc)
    return OutboundTaskRow(
        task_key=task_key,
        business_id=uuid4(),
        customer_id=uuid4(),
        contact_id=uuid4(),
        contact_name="Vendor 1",
        contact_role="vendor",
        initiated_by="customer",
        dispatch_prompt="ask vendor",
        state=state,  # type: ignore[arg-type]
        customer_context=None,
        system_context=None,
        dispatched_at=now,
        resolved_at=None,
        timeout_at=now + timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_deliver_party_reply_returns_when_task_missing(
    patch_ledger, monkeypatch
):
    patch_ledger.get_by_key = AsyncMock(return_value=None)
    run_mock = AsyncMock()
    monkeypatch.setattr(outbound.outbound_agent, "run", run_mock)

    await outbound.deliver_party_reply("nope", "hello")

    run_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_deliver_party_reply_returns_when_task_not_running(
    patch_ledger, monkeypatch
):
    patch_ledger.get_by_key = AsyncMock(
        return_value=_make_task_row(state="succeeded")
    )
    run_mock = AsyncMock()
    monkeypatch.setattr(outbound.outbound_agent, "run", run_mock)

    await outbound.deliver_party_reply("tk-done", "hello")

    run_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_deliver_party_reply_runs_agent_with_loaded_history(
    patch_ledger, patch_chat_storage, monkeypatch
):
    task = _make_task_row(task_key="tk-live")
    patch_ledger.get_by_key = AsyncMock(return_value=task)
    patch_chat_storage.load_outbound_history = AsyncMock(return_value=["prior"])

    captured: dict[str, Any] = {}

    async def _capture(prompt, deps, message_history=None):
        captured["prompt"] = prompt
        captured["deps_task_key"] = deps.task_key
        captured["history"] = message_history
        return SimpleNamespace(output="ok", new_messages=lambda: ["m1", "m2"])

    monkeypatch.setattr(
        outbound.outbound_agent, "run", AsyncMock(side_effect=_capture)
    )

    await outbound.deliver_party_reply("tk-live", "hello again")

    assert captured["prompt"] == "hello again"
    assert captured["deps_task_key"] == "tk-live"
    assert captured["history"] == ["prior"]
    patch_chat_storage.append_outbound_history.assert_awaited_once_with(
        "tk-live", ["m1", "m2"]
    )


@pytest.mark.asyncio
async def test_deliver_party_reply_marks_failed_on_agent_exception(
    patch_ledger, monkeypatch
):
    task = _make_task_row(task_key="tk-boom")
    patch_ledger.get_by_key = AsyncMock(return_value=task)

    async def _boom(prompt, deps, message_history=None):
        raise RuntimeError("model fell over")

    monkeypatch.setattr(outbound.outbound_agent, "run", AsyncMock(side_effect=_boom))

    await outbound.deliver_party_reply("tk-boom", "hi")

    patch_ledger.mark_failed.assert_awaited_once()
    assert (
        patch_ledger.mark_failed.await_args.kwargs["system_context"]
        == "model fell over"
    )


@pytest.mark.asyncio
async def test_deliver_party_reply_sends_ack_when_resolved(
    patch_ledger, patch_chat_storage, monkeypatch
):
    """When mark_completed flips state to 'succeeded', send the canned ack
    instead of the model's wrap-up text."""
    from datetime import datetime, timezone

    from backend.chatbot.channels.base import ChannelIdentity

    task = _make_task_row(task_key="tk-ack")
    patch_ledger.get_by_key = AsyncMock(return_value=task)
    # The post-run get_state lookup sees the resolved state.
    patch_ledger.get_state = AsyncMock(return_value="succeeded")

    monkeypatch.setattr(
        outbound.outbound_agent,
        "run",
        AsyncMock(
            return_value=SimpleNamespace(
                output="model wrap-up that should NOT be sent",
                new_messages=lambda: [],
            )
        ),
    )

    fake_identity = ChannelIdentity(
        business_id=str(task.business_id),
        customer_id=str(task.contact_id),
        channel="console",
        channel_user_id="vendor-addr",
        last_inbound_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        outbound, "_contact_identity", AsyncMock(return_value=fake_identity)
    )
    monkeypatch.setattr(
        outbound.registry, "get", lambda name: SimpleNamespace(send=AsyncMock())
    )

    dispatch_mock = AsyncMock()
    monkeypatch.setattr(
        outbound.messaging_dispatcher, "dispatch_to_party", dispatch_mock
    )

    result = await outbound.deliver_party_reply("tk-ack", "vendor reply")

    assert result is None
    dispatch_mock.assert_awaited_once()
    sent_text = dispatch_mock.await_args.args[2]
    assert sent_text == outbound._RESOLUTION_ACK_TEXT
    assert "model wrap-up" not in sent_text


@pytest.mark.asyncio
async def test_deliver_party_reply_returns_status_when_contact_deleted(
    patch_ledger, patch_chat_storage, monkeypatch
):
    """If the contact_id on the task row is None (contact deleted via SET NULL),
    deliver_party_reply must bail with a status string and never run the agent."""
    task = _make_task_row(task_key="tk-orphan")
    # Simulate the SET NULL after contact deletion.
    task = task.model_copy(update={"contact_id": None})
    patch_ledger.get_by_key = AsyncMock(return_value=task)
    run_mock = AsyncMock()
    monkeypatch.setattr(outbound.outbound_agent, "run", run_mock)

    result = await outbound.deliver_party_reply("tk-orphan", "vendor reply")

    assert result is not None
    assert "tk-orpha" in result  # task_key prefix appears
    assert "contact deleted" in result
    run_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_deliver_party_reply_silent_on_failed_state(
    patch_ledger, patch_chat_storage, monkeypatch
):
    """A non-succeeded terminal state (failed/cancelled) does NOT ack."""
    task = _make_task_row(task_key="tk-failed")
    patch_ledger.get_by_key = AsyncMock(return_value=task)
    patch_ledger.get_state = AsyncMock(return_value="failed")

    monkeypatch.setattr(
        outbound.outbound_agent,
        "run",
        AsyncMock(
            return_value=SimpleNamespace(output="x", new_messages=lambda: [])
        ),
    )
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(
        outbound.messaging_dispatcher, "dispatch_to_party", dispatch_mock
    )

    result = await outbound.deliver_party_reply("tk-failed", "vendor reply")

    assert result is None
    dispatch_mock.assert_not_awaited()


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
        contact_id=uuid4(),
        initiated_by="customer",
        dispatch_prompt="hi",
        parent_depth=parent_depth,
    )

    for _ in range(5):
        await asyncio.sleep(0)

    assert captured["deps"].current_depth == parent_depth + 1
