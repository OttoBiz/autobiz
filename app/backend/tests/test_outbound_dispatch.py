"""Tests for the outbound agent + dispatch helper.

The outbound module is the contact-side counterpart of central. The unit of
conversation is a contact; tasks are tags inside that conversation. Tests
mock the ledger, contacts, chat_storage, agent runs, transport, and the
contact_inbox lock — verifying the wiring without touching DB/Redis/LLM.
"""

from __future__ import annotations

import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "")

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from backend.chatbot.agents import outbound
from backend.db.contacts import Contact
from backend.db.outbound_ledger import OutboundTaskRow, OutboundTaskSummary

# Captured at import time so tests that need to exercise the real
# `_send_to_party` (e.g. event-ledger write coverage) can restore it past
# the autouse `patch_transport` fixture's AsyncMock.
_REAL_SEND_TO_PARTY = outbound._send_to_party


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


def _make_task_row(
    task_key: str = "tk-1",
    state: str = "running",
    summary: str = "ask vendor for stock",
) -> OutboundTaskRow:
    now = datetime.now(timezone.utc)
    return OutboundTaskRow(
        task_key=task_key,
        business_id=uuid4(),
        customer_id=uuid4(),
        contact_id=uuid4(),
        contact_name="Vendor 1",
        contact_role="vendor",
        initiated_by="customer",
        dispatch_prompt="ask vendor for stock",
        summary=summary,
        state=state,  # type: ignore[arg-type]
        customer_context=None,
        system_context=None,
        dispatched_at=now,
        resolved_at=None,
        timeout_at=now + timedelta(minutes=5),
    )


def _make_summary(task_key: str = "tk-1", summary: str = "ask vendor") -> OutboundTaskSummary:
    return OutboundTaskSummary(
        task_key=task_key,
        contact_role="vendor",
        summary=summary,
        dispatched_at=datetime.now(timezone.utc),
        customer_id=uuid4(),
    )


# ---------------------------------------------------------------------------
# Shared fixtures — every test needs a stubbed ledger, contacts, chat_storage,
# inbox lock, and transport. The agent.run is patched per-test.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def patch_contacts(monkeypatch):
    fake = SimpleNamespace(
        get_by_id=AsyncMock(side_effect=lambda cid: _make_contact()),
    )
    monkeypatch.setattr(outbound, "contacts", fake)
    return fake


@pytest.fixture(autouse=True)
def patch_ledger(monkeypatch):
    fake = SimpleNamespace(
        insert_task=AsyncMock(return_value=None),
        mark_running=AsyncMock(return_value=True),
        mark_completed=AsyncMock(return_value=True),
        mark_failed=AsyncMock(return_value=True),
        get_state=AsyncMock(return_value="running"),
        get_by_key=AsyncMock(return_value=None),
        list_open_tasks_by_contact=AsyncMock(return_value=[]),
        insert_task_update=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(outbound, "outbound_ledger", fake)
    return fake


@pytest.fixture(autouse=True)
def patch_events(monkeypatch):
    """Default: no-op events log + bump_tenant. Tests that exercise the
    multiparty ledger flow swap these with real fakes."""
    monkeypatch.setattr(outbound.events, "insert_event", AsyncMock(return_value=1))
    monkeypatch.setattr(outbound.events_search, "bump_tenant", lambda biz: None)


@pytest.fixture(autouse=True)
def patch_chat_storage(monkeypatch):
    fake = SimpleNamespace(
        load_contact_history=AsyncMock(return_value=[]),
        append_contact_history=AsyncMock(),
    )
    monkeypatch.setattr(outbound, "chat_storage", fake)
    return fake


@pytest.fixture(autouse=True)
def patch_redis_queue(monkeypatch):
    """Stub the per-contact mutex so dispatch's _run() proceeds immediately.

    The vendor-side lock now lives in `_redis_queue.acquire_lock` /
    `release_lock`; the unified inbox uses the same primitives.
    """
    monkeypatch.setattr(
        outbound._redis_queue, "acquire_lock", lambda key, owner, ttl_seconds: True
    )
    monkeypatch.setattr(
        outbound._redis_queue, "release_lock", lambda key, owner: True
    )


@pytest.fixture(autouse=True)
def patch_transport(monkeypatch):
    """Default the transport to no-op success — tests that care about the
    send path swap this with their own AsyncMock."""
    monkeypatch.setattr(outbound, "_send_to_party", AsyncMock(return_value=None))


def _ctx(deps: outbound.OutboundDeps | None = None) -> Any:
    if deps is None:
        deps = outbound.OutboundDeps(
            business_id=uuid4(),
            contact_id=uuid4(),
            contact_name="Vendor X",
            contact_role="vendor",
        )
    return SimpleNamespace(deps=deps)


# ---------------------------------------------------------------------------
# dispatch — opening run.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_inserts_ledger_row_and_returns_task_key(
    patch_ledger, patch_contacts, monkeypatch
):
    monkeypatch.setattr(
        outbound.outbound_agent,
        "run",
        AsyncMock(
            return_value=SimpleNamespace(output="ok", new_messages=lambda: [])
        ),
    )

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

    assert isinstance(task_key, str)
    assert len(task_key) == 32
    UUID(hex=task_key)

    patch_ledger.insert_task.assert_awaited_once()
    kwargs = patch_ledger.insert_task.await_args.kwargs
    assert kwargs["task_key"] == task_key
    assert kwargs["business_id"] == business_id
    assert kwargs["customer_id"] == customer_id
    assert kwargs["contact_id"] == contact.id
    assert kwargs["contact_name"] == contact.name
    assert kwargs["contact_role"] == contact.role
    assert kwargs["initiated_by"] == "customer"
    assert kwargs["dispatch_prompt"] == "ask vendor for stock"
    assert "summary" in kwargs
    assert "timeout_at" in kwargs

    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_dispatch_uses_provided_summary(patch_ledger, monkeypatch):
    monkeypatch.setattr(
        outbound.outbound_agent,
        "run",
        AsyncMock(
            return_value=SimpleNamespace(output="ok", new_messages=lambda: [])
        ),
    )

    await outbound.dispatch(
        business_id=uuid4(),
        customer_id=uuid4(),
        contact_id=uuid4(),
        initiated_by="customer",
        dispatch_prompt="ask vendor for stock — full long prompt body",
        summary="my custom headline",
    )

    kwargs = patch_ledger.insert_task.await_args.kwargs
    assert kwargs["summary"] == "my custom headline"

    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_dispatch_derives_summary_when_omitted(patch_ledger, monkeypatch):
    monkeypatch.setattr(
        outbound.outbound_agent,
        "run",
        AsyncMock(
            return_value=SimpleNamespace(output="ok", new_messages=lambda: [])
        ),
    )

    long_prompt = (
        "Please reach out to the vendor and find out whether they have the "
        "newest ankara collection in stock and what the wholesale price is."
    )

    await outbound.dispatch(
        business_id=uuid4(),
        customer_id=uuid4(),
        contact_id=uuid4(),
        initiated_by="customer",
        dispatch_prompt=long_prompt,
    )

    # No summary was passed — the harness uses the dispatch_prompt verbatim.
    # No synthetic truncation; the agent is responsible for shorter summaries
    # via the explicit `summary` kwarg when readability matters.
    summary = patch_ledger.insert_task.await_args.kwargs["summary"]
    assert summary == long_prompt

    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_dispatch_spawns_run_that_marks_running_then_runs_agent(
    patch_ledger, monkeypatch
):
    order: list[str] = []

    async def _mark_running(task_key: str) -> bool:
        order.append("mark_running")
        return True

    async def _run(prompt, deps, message_history=None):
        order.append("agent.run")
        return SimpleNamespace(output="hi vendor", new_messages=lambda: [])

    patch_ledger.mark_running = AsyncMock(side_effect=_mark_running)
    monkeypatch.setattr(outbound.outbound_agent, "run", AsyncMock(side_effect=_run))

    await outbound.dispatch(
        business_id=uuid4(),
        customer_id=uuid4(),
        contact_id=uuid4(),
        initiated_by="customer",
        dispatch_prompt="hi",
    )

    for _ in range(5):
        await asyncio.sleep(0)

    assert order == ["mark_running", "agent.run"]


@pytest.mark.asyncio
async def test_dispatch_marks_failed_on_agent_exception(patch_ledger, monkeypatch):
    async def _boom(prompt, deps, message_history=None):
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
async def test_dispatch_rejects_at_max_depth(patch_ledger, monkeypatch):
    monkeypatch.setattr(
        outbound.outbound_agent,
        "run",
        AsyncMock(return_value=SimpleNamespace(output="ok", new_messages=lambda: [])),
    )

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

    with pytest.raises(ValueError):
        await outbound.dispatch(
            business_id=uuid4(),
            customer_id=uuid4(),
            contact_id=uuid4(),
            initiated_by="customer",
            dispatch_prompt="hi",
            parent_depth=outbound.OUTBOUND_MAX_DEPTH,
        )


@pytest.mark.asyncio
async def test_dispatch_passes_current_depth_to_deps(patch_ledger, monkeypatch):
    captured: dict[str, Any] = {}

    async def _capture(prompt, deps, message_history=None):
        captured["deps"] = deps
        return SimpleNamespace(output="ok", new_messages=lambda: [])

    monkeypatch.setattr(outbound.outbound_agent, "run", AsyncMock(side_effect=_capture))

    await outbound.dispatch(
        business_id=uuid4(),
        customer_id=uuid4(),
        contact_id=uuid4(),
        initiated_by="customer",
        dispatch_prompt="hi",
        parent_depth=1,
    )

    for _ in range(5):
        await asyncio.sleep(0)

    assert captured["deps"].current_depth == 2


# ---------------------------------------------------------------------------
# share_update tool.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_share_update_accepts_only_amendable_rows(patch_ledger):
    # Two items: first ledger update succeeds, second fails (terminal state).
    patch_ledger.mark_completed = AsyncMock(side_effect=[True, False])

    items = [
        outbound.UpdateItem(task_key="tk-1", customer_context="answer 1"),
        outbound.UpdateItem(task_key="tk-2", customer_context="answer 2"),
    ]

    result = await outbound.share_update(_ctx(), items)

    assert result["skipped"] == ["tk-2"]
    assert [a["task_key"] for a in result["accepted"]] == ["tk-1"]
    assert result["accepted"][0]["customer_context"] == "answer 1"
    assert result["accepted"][0]["content_hash"] == outbound._content_hash("answer 1", None)
    assert patch_ledger.mark_completed.await_count == 2


@pytest.mark.asyncio
async def test_share_update_skips_items_with_no_context(patch_ledger):
    patch_ledger.mark_completed = AsyncMock(return_value=True)

    items = [
        outbound.UpdateItem(task_key="tk-empty", customer_context=None, system_context=None),
        outbound.UpdateItem(task_key="tk-keep", customer_context="ok"),
    ]

    result = await outbound.share_update(_ctx(), items)

    assert result["skipped"] == ["tk-empty"]
    assert [a["task_key"] for a in result["accepted"]] == ["tk-keep"]
    patch_ledger.mark_completed.assert_awaited_once_with("tk-keep", "ok", None)


@pytest.mark.asyncio
async def test_share_update_empty_input_returns_empty(patch_ledger):
    result = await outbound.share_update(_ctx(), [])
    assert result == {"accepted": [], "skipped": []}
    patch_ledger.mark_completed.assert_not_awaited()


@pytest.mark.asyncio
async def test_share_update_can_be_called_multiple_times_per_task(patch_ledger):
    """A vendor amendment fires share_update again with the same task_key.
    Both calls land on `accepted` with distinct content_hashes."""
    patch_ledger.mark_completed = AsyncMock(return_value=True)

    first = await outbound.share_update(
        _ctx(), [outbound.UpdateItem(task_key="tk-1", customer_context="10 in stock")]
    )
    second = await outbound.share_update(
        _ctx(), [outbound.UpdateItem(task_key="tk-1", customer_context="actually 5 in stock")]
    )

    assert first["accepted"][0]["task_key"] == "tk-1"
    assert second["accepted"][0]["task_key"] == "tk-1"
    assert (
        first["accepted"][0]["content_hash"] != second["accepted"][0]["content_hash"]
    ), "different payloads should hash differently"


@pytest.mark.asyncio
async def test_on_share_update_hook_appends_history_and_ingests(monkeypatch, patch_ledger):
    """The hook records each accepted update in outbound_task_updates and
    pushes a system_event to the customer inbox keyed on content_hash."""
    from backend.chatbot.conversations import inbox as conv_inbox

    task_a = _make_task_row(task_key="tk-a")
    task_b = _make_task_row(task_key="tk-b")
    by_key = {"tk-a": task_a, "tk-b": task_b}
    patch_ledger.get_by_key = AsyncMock(side_effect=lambda k: by_key.get(k))
    insert_history = AsyncMock(return_value=True)
    patch_ledger.insert_task_update = insert_history

    ingest_mock = MagicMock(return_value=True)
    monkeypatch.setattr(conv_inbox, "ingest", ingest_mock)

    accepted = [
        {
            "task_key": "tk-a",
            "customer_context": "answer-a",
            "system_context": None,
            "content_hash": "hash-a",
        },
        {
            "task_key": "tk-b",
            "customer_context": "answer-b",
            "system_context": None,
            "content_hash": "hash-b",
        },
    ]

    result = await outbound._on_share_update(
        _ctx(),
        call=None,
        tool_def=None,
        args={"items": []},
        result={"accepted": accepted, "skipped": []},
    )

    assert result["accepted"] == accepted
    assert insert_history.await_count == 2
    assert ingest_mock.call_count == 2
    summaries = sorted(
        call.args[1]["payload"]["summary"] for call in ingest_mock.call_args_list
    )
    assert summaries == ["answer-a", "answer-b"]
    # Dedup id includes task_key + content_hash so successive distinct
    # updates aren't squashed at the inbox.
    dedup_ids = sorted(call.kwargs["dedup_id"] for call in ingest_mock.call_args_list)
    assert dedup_ids == ["share:tk-a:hash-a", "share:tk-b:hash-b"]


@pytest.mark.asyncio
async def test_on_share_update_hook_skips_when_history_dedups(monkeypatch, patch_ledger):
    """When insert_task_update returns False (UNIQUE conflict), the hook
    must NOT re-push the customer event — the same payload was already
    forwarded once."""
    from backend.chatbot.conversations import inbox as conv_inbox

    patch_ledger.get_by_key = AsyncMock(return_value=_make_task_row("tk-dup"))
    patch_ledger.insert_task_update = AsyncMock(return_value=False)

    ingest_mock = MagicMock(return_value=True)
    monkeypatch.setattr(conv_inbox, "ingest", ingest_mock)

    await outbound._on_share_update(
        _ctx(),
        call=None,
        tool_def=None,
        args={"items": []},
        result={
            "accepted": [
                {
                    "task_key": "tk-dup",
                    "customer_context": "same payload",
                    "system_context": None,
                    "content_hash": "h",
                }
            ],
            "skipped": [],
        },
    )

    ingest_mock.assert_not_called()


@pytest.mark.asyncio
async def test_on_share_update_hook_skips_items_with_no_customer_context(
    monkeypatch, patch_ledger
):
    """Accepted updates with system_context only must record history but
    NOT enqueue a customer-side event."""
    from backend.chatbot.conversations import inbox as conv_inbox

    patch_ledger.get_by_key = AsyncMock(return_value=_make_task_row("tk-sysonly"))
    insert_history = AsyncMock(return_value=True)
    patch_ledger.insert_task_update = insert_history

    ingest_mock = MagicMock(return_value=True)
    monkeypatch.setattr(conv_inbox, "ingest", ingest_mock)

    await outbound._on_share_update(
        _ctx(),
        call=None,
        tool_def=None,
        args={"items": []},
        result={
            "accepted": [
                {
                    "task_key": "tk-sysonly",
                    "customer_context": None,
                    "system_context": "internal",
                    "content_hash": "h",
                }
            ],
            "skipped": [],
        },
    )

    insert_history.assert_awaited_once()
    ingest_mock.assert_not_called()


@pytest.mark.asyncio
async def test_on_share_update_hook_noop_when_nothing_accepted(monkeypatch):
    from backend.chatbot.conversations import inbox as conv_inbox

    ingest_mock = MagicMock()
    monkeypatch.setattr(conv_inbox, "ingest", ingest_mock)

    result = await outbound._on_share_update(
        _ctx(),
        call=None,
        tool_def=None,
        args={"items": []},
        result={"accepted": [], "skipped": ["tk-x"]},
    )

    assert result == {"accepted": [], "skipped": ["tk-x"]}
    ingest_mock.assert_not_called()


# ---------------------------------------------------------------------------
# get_task_details tool.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_task_details_returns_dispatch_prompt(patch_ledger):
    task = _make_task_row(task_key="tk-detail", summary="summary line")
    patch_ledger.get_by_key = AsyncMock(return_value=task)

    result = await outbound.get_task_details(_ctx(), "tk-detail")

    assert result is not None
    assert result["task_key"] == "tk-detail"
    assert result["dispatch_prompt"] == task.dispatch_prompt
    assert result["summary"] == "summary line"
    assert result["state"] == task.state
    assert "dispatched_at" in result


@pytest.mark.asyncio
async def test_get_task_details_returns_none_when_missing(patch_ledger):
    patch_ledger.get_by_key = AsyncMock(return_value=None)
    assert await outbound.get_task_details(_ctx(), "missing") is None


# ---------------------------------------------------------------------------
# Regression: vendor amendment after initial resolution must still reach the
# customer. Before this change, mark_completed gated on state='running' so
# the second share_update silently no-op'd, and the customer-inbox dedup_id
# was task-only so even bypassing the gate would have squashed the second
# event. This test exercises share_update + the after-tool hook end-to-end
# with an in-memory ledger to make sure both paths now flow through.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vendor_amendment_after_resolution_reaches_customer(
    monkeypatch, patch_ledger
):
    from backend.chatbot.conversations import inbox as conv_inbox

    # In-memory ledger: one task that starts in 'running'.
    state = {"state": "running", "customer_context": None, "system_context": None}
    history: list[tuple[str, str | None, str | None, str]] = []

    async def _mark_completed(task_key, customer_context, system_context):
        if state["state"] in ("running", "succeeded"):
            state["state"] = "succeeded"
            state["customer_context"] = customer_context
            state["system_context"] = system_context
            return True
        return False

    async def _insert_task_update(task_key, customer_context, system_context, content_hash):
        if any(h[3] == content_hash for h in history):
            return False
        history.append((task_key, customer_context, system_context, content_hash))
        return True

    task_row = _make_task_row(task_key="tk-amend")
    patch_ledger.mark_completed = AsyncMock(side_effect=_mark_completed)
    patch_ledger.insert_task_update = AsyncMock(side_effect=_insert_task_update)
    patch_ledger.get_by_key = AsyncMock(return_value=task_row)

    ingest_mock = MagicMock(return_value=True)
    monkeypatch.setattr(conv_inbox, "ingest", ingest_mock)

    # First reply: vendor says "10 in stock". share_update + hook.
    first = await outbound.share_update(
        _ctx(),
        [outbound.UpdateItem(task_key="tk-amend", customer_context="10 in stock")],
    )
    assert state["state"] == "succeeded"
    await outbound._on_share_update(
        _ctx(),
        call=None,
        tool_def=None,
        args={},
        result=first,
    )

    # Second reply: vendor amends — "actually only 5". The state is already
    # 'succeeded', but mark_completed must still accept and the hook must
    # still fire a fresh customer event with a different dedup_id.
    second = await outbound.share_update(
        _ctx(),
        [outbound.UpdateItem(task_key="tk-amend", customer_context="actually only 5")],
    )
    assert second["accepted"], "amendment must be accepted, not skipped"
    await outbound._on_share_update(
        _ctx(),
        call=None,
        tool_def=None,
        args={},
        result=second,
    )

    # Both updates landed in history with distinct hashes.
    assert len(history) == 2
    assert {h[1] for h in history} == {"10 in stock", "actually only 5"}
    assert history[0][3] != history[1][3]

    # Customer inbox received TWO distinct system_events.
    assert ingest_mock.call_count == 2
    summaries = [c.args[1]["payload"]["summary"] for c in ingest_mock.call_args_list]
    assert summaries == ["10 in stock", "actually only 5"]
    dedups = [c.kwargs["dedup_id"] for c in ingest_mock.call_args_list]
    assert dedups[0] != dedups[1]

    # Repeating the SAME amendment a third time must dedup at history and
    # NOT push a third customer event.
    third = await outbound.share_update(
        _ctx(),
        [outbound.UpdateItem(task_key="tk-amend", customer_context="actually only 5")],
    )
    await outbound._on_share_update(
        _ctx(), call=None, tool_def=None, args={}, result=third
    )
    assert len(history) == 2
    assert ingest_mock.call_count == 2


# ---------------------------------------------------------------------------
# deliver_contact_reply — drain runner entry point.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_contact_reply_runs_agent_with_manifest_and_history(
    patch_ledger, patch_chat_storage, patch_contacts, monkeypatch
):
    biz = uuid4()
    contact = _make_contact(business_id=biz)
    patch_contacts.get_by_id = AsyncMock(return_value=contact)

    summaries = [_make_summary(task_key="tk-A"), _make_summary(task_key="tk-B")]
    patch_ledger.list_open_tasks_by_contact = AsyncMock(return_value=summaries)

    patch_chat_storage.load_contact_history = AsyncMock(return_value=["prior"])

    captured: dict[str, Any] = {}

    async def _run(prompt, deps, message_history=None):
        captured["prompt"] = prompt
        captured["deps"] = deps
        captured["history"] = message_history
        return SimpleNamespace(
            output="thanks, will let the customer know",
            new_messages=lambda: ["m1", "m2"],
        )

    monkeypatch.setattr(outbound.outbound_agent, "run", AsyncMock(side_effect=_run))

    send_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(outbound, "_send_to_party", send_mock)

    result = await outbound.deliver_contact_reply(
        biz, contact.id, ["hello", "5 in stock"]
    )

    assert result is None
    assert captured["prompt"] == "hello\n5 in stock"
    assert captured["history"] == ["prior"]
    assert captured["deps"].open_tasks == summaries
    assert captured["deps"].business_id == biz
    assert captured["deps"].contact_id == contact.id

    patch_chat_storage.append_contact_history.assert_awaited_once_with(
        biz, contact.id, ["m1", "m2"]
    )
    send_mock.assert_awaited_once()
    send_kwargs = send_mock.await_args.kwargs
    assert send_kwargs["contact_id"] == contact.id
    assert send_kwargs["text"] == "thanks, will let the customer know"


@pytest.mark.asyncio
async def test_deliver_contact_reply_returns_status_on_unknown_contact(
    patch_contacts, monkeypatch
):
    patch_contacts.get_by_id = AsyncMock(return_value=None)
    run_mock = AsyncMock()
    monkeypatch.setattr(outbound.outbound_agent, "run", run_mock)

    result = await outbound.deliver_contact_reply(uuid4(), uuid4(), ["hi"])

    assert isinstance(result, str)
    assert "not found" in result
    run_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_deliver_contact_reply_returns_status_on_cross_tenant_contact(
    patch_contacts, monkeypatch
):
    # Contact belongs to a different business than the one supplied.
    contact = _make_contact(business_id=uuid4())
    patch_contacts.get_by_id = AsyncMock(return_value=contact)
    run_mock = AsyncMock()
    monkeypatch.setattr(outbound.outbound_agent, "run", run_mock)

    result = await outbound.deliver_contact_reply(uuid4(), contact.id, ["hi"])

    assert isinstance(result, str)
    assert "doesn't belong" in result
    run_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_deliver_contact_reply_handles_empty_messages_list(
    patch_contacts, monkeypatch
):
    biz = uuid4()
    contact = _make_contact(business_id=biz)
    patch_contacts.get_by_id = AsyncMock(return_value=contact)

    run_mock = AsyncMock()
    monkeypatch.setattr(outbound.outbound_agent, "run", run_mock)

    # Both empty list and list of empty strings should return a status without
    # running the agent.
    result_empty = await outbound.deliver_contact_reply(biz, contact.id, [])
    assert isinstance(result_empty, str)
    assert "empty inbound" in result_empty

    result_blank = await outbound.deliver_contact_reply(biz, contact.id, ["", "   "])
    assert isinstance(result_blank, str)
    assert "empty inbound" in result_blank

    run_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# find_customer_context — agent's search-driven disambiguation tool.
# Exercises the full ledger write → bm25 search → cluster expansion path
# through the real events_search module (no stubs at the search layer).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_customer_context_disambiguates_two_customers_via_ledger(
    monkeypatch,
):
    """Multi-customer vendor scenario from the screenshot.

    A vendor handles orders for two customers. We seed the ledger with
    distinct events per customer, then call find_customer_context with a
    phrase only one customer's events match. The tool must return that
    customer first with their recent events expanded.
    """
    from backend.db import events as events_db
    from backend.db import events_search

    biz = uuid4()
    customer_oxford = uuid4()
    customer_ankara = uuid4()
    contact_id = uuid4()

    # Seed the in-memory event store the search reads from.
    seeded: list[events_db.EventRow] = []

    def _seed(
        customer_id: UUID | None,
        content: str,
        actor: str = "contact",
        direction: str = "in",
        age_minutes: int = 5,
    ) -> None:
        seeded.append(
            events_db.EventRow(
                id=len(seeded) + 1,
                business_id=biz,
                customer_id=customer_id,
                contact_id=contact_id,
                task_key=None,
                thread_id=f"contact:{contact_id}",
                actor=actor,  # type: ignore[arg-type]
                direction=direction,  # type: ignore[arg-type]
                content=content,
                provider_message_id=None,
                created_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
            )
        )

    _seed(
        customer_oxford,
        "customer asked about Oxford shoes size 15 for 1 Justice Coker Estate",
        actor="customer",
        age_minutes=20,
    )
    _seed(
        customer_oxford,
        "dispatched Oxford shoes order to vendor",
        actor="business",
        direction="out",
        age_minutes=18,
    )
    _seed(
        customer_ankara,
        "customer asked about ankara fabric purple 6 yards",
        actor="customer",
        age_minutes=15,
    )

    async def fake_list(business_id, *, limit=5000):
        return [r for r in seeded if r.business_id == business_id]

    async def fake_list_for_customer(business_id, customer_id, *, limit=20):
        return [
            r
            for r in seeded
            if r.business_id == business_id and r.customer_id == customer_id
        ][:limit]

    monkeypatch.setattr(events_db, "list_recent_for_business", fake_list)
    monkeypatch.setattr(events_db, "list_recent_for_customer", fake_list_for_customer)

    # Stub the per-cluster expansion lookups.
    from backend.db import db_utils, outbound_ledger

    async def fake_user(uid):
        if uid == str(customer_oxford):
            return {"id": uid, "name": "Alice (Oxford order)"}
        if uid == str(customer_ankara):
            return {"id": uid, "name": "Bola (Ankara order)"}
        return None

    monkeypatch.setattr(db_utils, "get_user_by_id", fake_user)
    monkeypatch.setattr(
        outbound_ledger, "get_pending_for_customer", AsyncMock(return_value=[])
    )

    # Reset search caches so this test is hermetic.
    events_search._versions.clear()
    events_search._indexes.clear()
    events_search.bump_tenant(biz)

    deps = outbound.OutboundDeps(
        business_id=biz,
        contact_id=contact_id,
        contact_name="Vendor X",
        contact_role="vendor",
    )
    ctx = SimpleNamespace(deps=deps)

    # Vendor reply was: "address noted, delivery going out for the size 15".
    # Agent searches with the distinguishing phrase.
    results = await outbound.find_customer_context(
        ctx, "size 15 1 Justice Coker delivery", limit=3
    )

    assert results, "search must return at least one cluster"
    top = results[0]
    assert top["customer_id"] == str(customer_oxford), (
        f"Oxford customer must rank first; got {top['customer_id']}"
    )
    assert top["customer_name"] == "Alice (Oxford order)"
    # Recent events for the matched customer are surfaced for context.
    contents = [e["content"] for e in top["recent_events"]]
    assert any("Oxford" in c for c in contents)
    # The unrelated customer's events must NOT bleed into the top cluster.
    assert not any("ankara" in c.lower() for c in contents)


@pytest.mark.asyncio
async def test_send_to_party_writes_to_event_ledger(monkeypatch):
    """Outbound vendor send must append a 'business→contact' event row."""
    # Restore the real _send_to_party past the autouse `patch_transport`
    # mock, so this test exercises the actual ledger-write code path.
    monkeypatch.setattr(outbound, "_send_to_party", _REAL_SEND_TO_PARTY)

    inserted: list[dict[str, Any]] = []

    async def _capture(**kwargs):
        inserted.append(kwargs)
        return 1

    monkeypatch.setattr(outbound.events, "insert_event", _capture)
    bumps: list[UUID] = []
    monkeypatch.setattr(
        outbound.events_search, "bump_tenant", lambda biz: bumps.append(biz)
    )

    biz = uuid4()
    contact_id = uuid4()
    customer_id = uuid4()

    monkeypatch.setattr(
        outbound,
        "_contact_identity",
        AsyncMock(
            return_value=outbound.ChannelIdentity(
                business_id=str(biz),
                customer_id=str(contact_id),
                channel="console",
                channel_user_id="vendor-wa-1",
                last_inbound_at=None,
                channel_business_id=None,
            )
        ),
    )

    # Stub channel send + dispatcher so transport doesn't actually fire.
    fake_channel = SimpleNamespace(send=AsyncMock(return_value=None))
    monkeypatch.setattr(outbound.registry, "get", lambda channel_name: fake_channel)
    monkeypatch.setattr(
        outbound.messaging_dispatcher,
        "dispatch_to_party",
        AsyncMock(return_value=None),
    )

    status = await outbound._send_to_party(
        business_id=biz,
        contact_id=contact_id,
        text="hi vendor please confirm size",
        task_key="tk-XYZ",
        customer_id=customer_id,
    )

    assert status is None
    assert len(inserted) == 1
    row = inserted[0]
    assert row["business_id"] == biz
    assert row["actor"] == "business"
    assert row["direction"] == "out"
    assert row["thread_id"] == f"contact:{contact_id}"
    assert row["content"] == "hi vendor please confirm size"
    assert row["customer_id"] == customer_id
    assert row["contact_id"] == contact_id
    assert row["task_key"] == "tk-XYZ"
    assert bumps == [biz], "tenant cache must be bumped after a send"


@pytest.mark.asyncio
async def test_deliver_contact_reply_logs_inbound_to_ledger(
    patch_ledger, patch_chat_storage, patch_contacts, monkeypatch
):
    """Vendor inbound text logged to events BEFORE agent run, so a
    find_customer_context call inside the run can see it."""
    biz = uuid4()
    contact = _make_contact(business_id=biz)
    patch_contacts.get_by_id = AsyncMock(return_value=contact)

    inserted: list[dict[str, Any]] = []

    async def _capture(**kwargs):
        inserted.append(kwargs)
        return len(inserted)

    monkeypatch.setattr(outbound.events, "insert_event", _capture)
    monkeypatch.setattr(outbound.events_search, "bump_tenant", lambda biz: None)

    monkeypatch.setattr(
        outbound.outbound_agent,
        "run",
        AsyncMock(return_value=SimpleNamespace(output="ack", new_messages=lambda: [])),
    )
    monkeypatch.setattr(outbound, "_send_to_party", AsyncMock(return_value=None))

    await outbound.deliver_contact_reply(
        biz, contact.id, ["address noted", "delivery going out today"]
    )

    # Both inbound messages logged with actor=contact, direction=in.
    inbound_only = [r for r in inserted if r["actor"] == "contact" and r["direction"] == "in"]
    assert len(inbound_only) == 2
    contents = [r["content"] for r in inbound_only]
    assert "address noted" in contents
    assert "delivery going out today" in contents
    # customer_id is NULL on inbound (agent resolves via search).
    assert all(r.get("customer_id") is None for r in inbound_only)
    assert all(r["thread_id"] == f"contact:{contact.id}" for r in inbound_only)


# ---------------------------------------------------------------------------
# Hooks registry sanity check.
# ---------------------------------------------------------------------------


def test_hooks_registered_on_agent():
    registry = outbound._hooks._registry
    assert "after_tool_execute" in registry
    after_entries = registry["after_tool_execute"]
    assert any("share_update" in (e.tools or ()) for e in after_entries)
