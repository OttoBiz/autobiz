"""Tests for the outbound agent + dispatch helper.

Outbound module is the contact-side counterpart of central. The unit of
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
from backend.db.outbound_ledger import (
    LogWriteError,
    OutboundTaskRow,
    OutboundTaskSummary,
)

# Captured at import time so tests that need the real `_send_to_party`
# can restore it past the autouse `patch_transport` fixture's AsyncMock.
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
    log: str = "## Dispatched\nBrief: ask vendor for stock",
    closed_at: datetime | None = None,
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
        log=log,
        dispatched_at=now,
        timeout_at=now + timedelta(minutes=5),
        closed_at=closed_at,
    )


def _make_summary(
    task_key: str = "tk-1", log_excerpt: str = "## Dispatched\nBrief: ask vendor"
) -> OutboundTaskSummary:
    return OutboundTaskSummary(
        task_key=task_key,
        contact_role="vendor",
        log_excerpt=log_excerpt,
        dispatched_at=datetime.now(timezone.utc),
        customer_id=uuid4(),
    )


# ---------------------------------------------------------------------------
# Fixtures
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
        close_task=AsyncMock(return_value=True),
        get_by_key=AsyncMock(return_value=None),
        list_open_tasks_by_contact=AsyncMock(return_value=[]),
        append_to_log=AsyncMock(return_value="updated log"),
        replace_in_log=AsyncMock(return_value="updated log"),
        remove_from_log=AsyncMock(return_value="updated log"),
        append_if_open_and_not_recent_dup=AsyncMock(return_value=(True, None)),
        find_tasks=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(outbound, "outbound_ledger", fake)
    return fake


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
    monkeypatch.setattr(
        outbound._redis_queue, "acquire_lock", lambda key, owner, ttl_seconds: True
    )
    monkeypatch.setattr(
        outbound._redis_queue, "release_lock", lambda key, owner: True
    )


@pytest.fixture(autouse=True)
def patch_transport(monkeypatch):
    """Default transport to no-op success — tests that need to exercise the
    real send path swap with `_REAL_SEND_TO_PARTY`."""
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
# dispatch — opening run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_inserts_task_with_seeded_log(patch_ledger, patch_contacts, monkeypatch):
    monkeypatch.setattr(
        outbound.outbound_agent,
        "run",
        AsyncMock(return_value=SimpleNamespace(output="ok", new_messages=lambda: [])),
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
    )

    assert isinstance(task_key, str)
    assert len(task_key) == 32
    UUID(hex=task_key)
    patch_ledger.insert_task.assert_awaited_once()
    kwargs = patch_ledger.insert_task.await_args.kwargs
    assert kwargs["task_key"] == task_key
    assert kwargs["business_id"] == business_id
    assert kwargs["customer_id"] == customer_id
    assert kwargs["dispatch_prompt"] == "ask vendor for stock"
    # No `summary` kwarg in the new signature.
    assert "summary" not in kwargs

    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_dispatch_closes_task_on_agent_exception(patch_ledger, monkeypatch):
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

    patch_ledger.close_task.assert_awaited_once()
    kwargs = patch_ledger.close_task.await_args.kwargs
    assert kwargs["reason"] == "dispatch_failed"
    assert "model exploded" in kwargs["final_log_entry"]


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


# ---------------------------------------------------------------------------
# share_update — log append + customer fan-out wrapper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_share_update_accepts_open_task_with_relay(patch_ledger):
    patch_ledger.append_if_open_and_not_recent_dup = AsyncMock(return_value=(True, None))
    items = [
        outbound.UpdateItem(task_key="tk-1", relay_to_customer="vendor confirmed size 15"),
    ]
    result = await outbound.share_update(_ctx(), items)

    assert result["skipped"] == []
    assert len(result["accepted"]) == 1
    accepted = result["accepted"][0]
    assert accepted["task_key"] == "tk-1"
    assert accepted["relay_to_customer"] == "vendor confirmed size 15"
    assert accepted["content_hash"] == outbound._content_hash("vendor confirmed size 15")

    # Wrapper called the ledger primitive with a section that includes the relay text.
    section = patch_ledger.append_if_open_and_not_recent_dup.await_args.args[1]
    assert "## Relayed to customer" in section
    assert "vendor confirmed size 15" in section


@pytest.mark.asyncio
async def test_share_update_skips_closed_task(patch_ledger):
    patch_ledger.append_if_open_and_not_recent_dup = AsyncMock(return_value=(False, "task_closed"))
    items = [outbound.UpdateItem(task_key="tk-closed", relay_to_customer="late update")]
    result = await outbound.share_update(_ctx(), items)
    assert result["accepted"] == []
    assert result["skipped"] == [{"task_key": "tk-closed", "reason": "task_closed"}]


@pytest.mark.asyncio
async def test_share_update_skips_duplicate_relay(patch_ledger):
    patch_ledger.append_if_open_and_not_recent_dup = AsyncMock(
        return_value=(False, "duplicate_recent_relay")
    )
    items = [outbound.UpdateItem(task_key="tk-1", relay_to_customer="same as before")]
    result = await outbound.share_update(_ctx(), items)
    assert result["skipped"] == [{"task_key": "tk-1", "reason": "duplicate_recent_relay"}]


@pytest.mark.asyncio
async def test_share_update_skips_empty_payload(patch_ledger):
    items = [outbound.UpdateItem(task_key="tk-1", relay_to_customer=None, system_note=None)]
    result = await outbound.share_update(_ctx(), items)
    assert result["skipped"] == [{"task_key": "tk-1", "reason": "empty_payload"}]
    patch_ledger.append_if_open_and_not_recent_dup.assert_not_awaited()


@pytest.mark.asyncio
async def test_share_update_can_fire_twice_on_same_task(patch_ledger):
    """Vendor amends the same task — second share_update goes through with
    a different content hash + a new ledger append."""
    patch_ledger.append_if_open_and_not_recent_dup = AsyncMock(return_value=(True, None))

    first = await outbound.share_update(
        _ctx(),
        [outbound.UpdateItem(task_key="tk-1", relay_to_customer="10 in stock")],
    )
    second = await outbound.share_update(
        _ctx(),
        [outbound.UpdateItem(task_key="tk-1", relay_to_customer="actually only 5 in stock")],
    )

    assert first["accepted"][0]["task_key"] == "tk-1"
    assert second["accepted"][0]["task_key"] == "tk-1"
    assert (
        first["accepted"][0]["content_hash"]
        != second["accepted"][0]["content_hash"]
    ), "different relay text → different hash"
    assert patch_ledger.append_if_open_and_not_recent_dup.await_count == 2


# ---------------------------------------------------------------------------
# _on_share_update hook — customer fan-out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_share_update_hook_fans_out_to_customer(monkeypatch, patch_ledger):
    from backend.chatbot.conversations import inbox as conv_inbox

    task = _make_task_row(task_key="tk-a")
    patch_ledger.get_by_key = AsyncMock(return_value=task)

    ingest_mock = MagicMock(return_value=True)
    monkeypatch.setattr(conv_inbox, "ingest", ingest_mock)

    accepted = [
        {
            "task_key": "tk-a",
            "relay_to_customer": "answer-a",
            "system_note": None,
            "content_hash": "hash-a",
        },
    ]
    result = await outbound._on_share_update(
        _ctx(), call=None, tool_def=None, args={}, result={"accepted": accepted, "skipped": []}
    )
    assert result == {"accepted": accepted, "skipped": []}
    assert ingest_mock.call_count == 1
    summary = ingest_mock.call_args.args[1]["payload"]["summary"]
    assert summary == "answer-a"
    dedup = ingest_mock.call_args.kwargs["dedup_id"]
    assert dedup == "share:tk-a:hash-a"


@pytest.mark.asyncio
async def test_on_share_update_hook_skips_items_without_relay(monkeypatch, patch_ledger):
    """system_note-only items don't fan out (the log already captured them)."""
    from backend.chatbot.conversations import inbox as conv_inbox

    patch_ledger.get_by_key = AsyncMock(return_value=_make_task_row("tk-sys"))
    ingest_mock = MagicMock(return_value=True)
    monkeypatch.setattr(conv_inbox, "ingest", ingest_mock)

    await outbound._on_share_update(
        _ctx(),
        call=None,
        tool_def=None,
        args={},
        result={
            "accepted": [
                {
                    "task_key": "tk-sys",
                    "relay_to_customer": None,
                    "system_note": "internal note",
                    "content_hash": "h",
                }
            ],
            "skipped": [],
        },
    )
    ingest_mock.assert_not_called()


@pytest.mark.asyncio
async def test_on_share_update_hook_noop_when_nothing_accepted(monkeypatch):
    from backend.chatbot.conversations import inbox as conv_inbox

    ingest_mock = MagicMock()
    monkeypatch.setattr(conv_inbox, "ingest", ingest_mock)
    result = await outbound._on_share_update(
        _ctx(), call=None, tool_def=None, args={}, result={"accepted": [], "skipped": []}
    )
    assert result == {"accepted": [], "skipped": []}
    ingest_mock.assert_not_called()


# ---------------------------------------------------------------------------
# update_task_log — Hermes-style CRUD wrapper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_task_log_add_calls_append(patch_ledger):
    result = await outbound.update_task_log(_ctx(), "tk-1", "add", "## new\nentry")
    assert result["ok"] is True
    patch_ledger.append_to_log.assert_awaited_once_with("tk-1", "## new\nentry")


@pytest.mark.asyncio
async def test_update_task_log_replace_requires_old_text(patch_ledger):
    result = await outbound.update_task_log(_ctx(), "tk-1", "replace", "new", old_text=None)
    assert result["ok"] is False
    assert result["reason"] == "old_text_required"


@pytest.mark.asyncio
async def test_update_task_log_replace_calls_replace(patch_ledger):
    await outbound.update_task_log(_ctx(), "tk-1", "replace", "new", old_text="old")
    patch_ledger.replace_in_log.assert_awaited_once_with("tk-1", "old", "new")


@pytest.mark.asyncio
async def test_update_task_log_remove_uses_old_text_or_content(patch_ledger):
    await outbound.update_task_log(_ctx(), "tk-1", "remove", "", old_text="target")
    patch_ledger.remove_from_log.assert_awaited_once_with("tk-1", "target")


@pytest.mark.asyncio
async def test_update_task_log_returns_reason_on_log_write_error(patch_ledger):
    patch_ledger.append_to_log = AsyncMock(side_effect=LogWriteError("log_cap_exceeded"))
    result = await outbound.update_task_log(_ctx(), "tk-1", "add", "stuff")
    assert result["ok"] is False
    assert "log_cap_exceeded" in result["reason"]


# ---------------------------------------------------------------------------
# close_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_task_calls_ledger(patch_ledger):
    result = await outbound.close_task(_ctx(), "tk-1", reason="delivered")
    assert result == {"ok": True}
    patch_ledger.close_task.assert_awaited_once_with(
        "tk-1", reason="delivered", final_log_entry=None
    )


@pytest.mark.asyncio
async def test_close_task_returns_reason_on_already_closed(patch_ledger):
    patch_ledger.close_task = AsyncMock(return_value=False)
    result = await outbound.close_task(_ctx(), "tk-1", reason="x")
    assert result == {"ok": False, "reason": "already_closed_or_unknown"}


# ---------------------------------------------------------------------------
# find_tasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_tasks_returns_serialized_rows(patch_ledger):
    biz = uuid4()
    cust = uuid4()
    contact = uuid4()
    row = OutboundTaskRow(
        task_key="tk-find",
        business_id=biz,
        customer_id=cust,
        contact_id=contact,
        contact_name="Vendor X",
        contact_role="vendor",
        initiated_by="customer",
        log="## Dispatched\nBrief: oxford 15",
        dispatched_at=datetime.now(timezone.utc),
        timeout_at=datetime.now(timezone.utc) + timedelta(hours=1),
        closed_at=None,
    )
    patch_ledger.find_tasks = AsyncMock(return_value=[row])

    deps = outbound.OutboundDeps(
        business_id=biz,
        contact_id=contact,
        contact_name="Vendor X",
        contact_role="vendor",
    )
    result = await outbound.find_tasks(_ctx(deps), "oxford size 15")
    assert len(result) == 1
    assert result[0]["task_key"] == "tk-find"
    assert result[0]["customer_id"] == str(cust)
    assert result[0]["log"].startswith("## Dispatched")
    assert result[0]["closed_at"] is None
    patch_ledger.find_tasks.assert_awaited_once_with(
        biz, "oxford size 15", customer_id=None, contact_id=None, limit=5
    )


# ---------------------------------------------------------------------------
# get_task_details
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_task_details_returns_full_log(patch_ledger):
    task = _make_task_row(task_key="tk-detail", log="## Dispatched\nBrief: detail check")
    patch_ledger.get_by_key = AsyncMock(return_value=task)
    result = await outbound.get_task_details(_ctx(), "tk-detail")
    assert result is not None
    assert result["task_key"] == "tk-detail"
    assert result["log"] == "## Dispatched\nBrief: detail check"
    assert result["closed_at"] is None


@pytest.mark.asyncio
async def test_get_task_details_returns_none_when_missing(patch_ledger):
    patch_ledger.get_by_key = AsyncMock(return_value=None)
    assert await outbound.get_task_details(_ctx(), "missing") is None


# ---------------------------------------------------------------------------
# surface_to_customer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_surface_to_customer_uses_explicit_customer_id(monkeypatch):
    from backend.chatbot.conversations import inbox as conv_inbox

    explicit = uuid4()
    deps = outbound.OutboundDeps(
        business_id=uuid4(),
        contact_id=uuid4(),
        contact_name="Vendor X",
        contact_role="vendor",
        customer_id=None,  # no deps binding
    )
    ingest_mock = MagicMock(return_value=True)
    monkeypatch.setattr(conv_inbox, "ingest", ingest_mock)

    result = await outbound.surface_to_customer(_ctx(deps), "follow-up note", customer_id=explicit)
    assert result == {"ok": True}
    party = ingest_mock.call_args.args[0]
    assert party.kind == "customer"
    assert party.party_id == str(explicit)


@pytest.mark.asyncio
async def test_surface_to_customer_returns_no_customer_when_unbound():
    deps = outbound.OutboundDeps(
        business_id=uuid4(),
        contact_id=uuid4(),
        contact_name="Vendor X",
        contact_role="vendor",
    )
    result = await outbound.surface_to_customer(_ctx(deps), "msg")
    assert result == {"ok": False, "reason": "no_customer_context"}


# ---------------------------------------------------------------------------
# deliver_contact_reply — reply-run entry point
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_contact_reply_runs_agent_with_manifest(
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
        return SimpleNamespace(output="thanks vendor", new_messages=lambda: [])

    monkeypatch.setattr(outbound.outbound_agent, "run", AsyncMock(side_effect=_run))
    send_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(outbound, "_send_to_party", send_mock)

    result = await outbound.deliver_contact_reply(biz, contact.id, ["got it", "5 in stock"])
    assert result is None
    assert captured["prompt"] == "got it\n5 in stock"
    assert captured["deps"].open_tasks == summaries
    send_mock.assert_awaited_once()


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


# ---------------------------------------------------------------------------
# Regression: vendor amendment flow — log + dedup + customer fan-out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_vendor_amendment_then_relay_dedup(monkeypatch, patch_ledger):
    """Vendor sends initial reply → share_update fires; then sends an
    amendment → share_update fires again (different hash); same payload
    fired a third time → ledger dedup blocks the log + customer fan-out."""
    from backend.chatbot.conversations import inbox as conv_inbox

    appended_state: list[str] = []

    async def fake_append_if_open(task_key, section):
        body = "\n".join(section.split("\n")[1:]).strip()
        if any(body in s for s in appended_state):
            return False, "duplicate_recent_relay"
        appended_state.append(section)
        return True, None

    patch_ledger.append_if_open_and_not_recent_dup = AsyncMock(side_effect=fake_append_if_open)
    patch_ledger.get_by_key = AsyncMock(return_value=_make_task_row("tk-A"))

    ingest_mock = MagicMock(return_value=True)
    monkeypatch.setattr(conv_inbox, "ingest", ingest_mock)

    # First reply.
    first = await outbound.share_update(
        _ctx(), [outbound.UpdateItem(task_key="tk-A", relay_to_customer="10 in stock")]
    )
    await outbound._on_share_update(
        _ctx(), call=None, tool_def=None, args={}, result=first
    )

    # Amendment.
    second = await outbound.share_update(
        _ctx(), [outbound.UpdateItem(task_key="tk-A", relay_to_customer="actually only 5")]
    )
    await outbound._on_share_update(
        _ctx(), call=None, tool_def=None, args={}, result=second
    )

    # Repeat the amendment — must dedup.
    third = await outbound.share_update(
        _ctx(), [outbound.UpdateItem(task_key="tk-A", relay_to_customer="actually only 5")]
    )
    await outbound._on_share_update(
        _ctx(), call=None, tool_def=None, args={}, result=third
    )

    assert len(first["accepted"]) == 1
    assert len(second["accepted"]) == 1
    assert third["accepted"] == []
    assert third["skipped"][0]["reason"] == "duplicate_recent_relay"

    # Customer received exactly two distinct system_events.
    assert ingest_mock.call_count == 2
    summaries = [c.args[1]["payload"]["summary"] for c in ingest_mock.call_args_list]
    assert summaries == ["10 in stock", "actually only 5"]


# ---------------------------------------------------------------------------
# Hooks registry sanity check.
# ---------------------------------------------------------------------------


def test_hooks_registered_on_agent():
    registry = outbound._hooks._registry
    assert "after_tool_execute" in registry
    after_entries = registry["after_tool_execute"]
    assert any("share_update" in (e.tools or ()) for e in after_entries)
