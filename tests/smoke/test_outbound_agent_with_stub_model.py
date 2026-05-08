"""Stub-model harness for outbound_agent.

Drives the real pydantic-ai agent loop against `FunctionModel` — a scripted
"model" that returns predetermined tool calls + text — while keeping every
other layer live: real Postgres + outbound_ledger writes, real Redis
inbox.ingest dedup, real bm25s search.

This proves the prompt → tool-choice → ledger-write chain end-to-end
without needing an LLM key. Each test scripts the model's per-turn
response, runs `outbound_agent.run`, and asserts on what the system did
afterwards (DB state + customer-side inbox events).

Pre-reqs (same as test_outbound_log_flow.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ottobiz
    REDIS_URL=redis://:redispassword@localhost:6379/0

Run from repo root:
    pytest tests/smoke/test_outbound_agent_with_stub_model.py -xvs
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

# app/ on path so direct imports work when running from repo root.
_APP = Path(__file__).resolve().parents[2] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "redispassword")
os.environ.setdefault(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ottobiz"
)


# ---------------------------------------------------------------------------
# Test fixture: real DB + tenancy seed (same shape as test_outbound_log_flow)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="session")
async def db_ready(smoke_tenancy):
    """Alias for the shared session-scoped fixture in conftest.py."""
    return smoke_tenancy


# ---------------------------------------------------------------------------
# Helpers — script-driven FunctionModel
# ---------------------------------------------------------------------------


def _last_tool_returns(messages: list[ModelMessage]) -> list[tuple[str, object]]:
    """Extract (tool_name, content) pairs from the most recent ModelRequest's
    ToolReturnParts. The agent loop appends one ModelRequest per round of
    tool returns, then asks the model what to do next. We use these to
    decide branching in the script."""
    pairs: list[tuple[str, object]] = []
    for msg in reversed(messages):
        if not isinstance(msg, ModelRequest):
            continue
        for p in msg.parts:
            if isinstance(p, ToolReturnPart):
                content = p.content
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except (TypeError, ValueError):
                        pass
                pairs.append((p.tool_name, content))
        if pairs:
            return pairs
    return []


def _all_tool_call_names(messages: list[ModelMessage]) -> list[str]:
    """Names of every tool the model has called so far in this run."""
    names: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelResponse):
            for p in msg.parts:
                if isinstance(p, ToolCallPart):
                    names.append(p.tool_name)
    return names


def _make_deps(
    business_id: UUID, contact_id: UUID, customer_id: UUID | None, open_tasks: list
):
    from backend.chatbot.agents.outbound import OutboundDeps

    return OutboundDeps(
        business_id=business_id,
        contact_id=contact_id,
        contact_name="Vendor X",
        contact_role="vendor",
        customer_id=customer_id,
        open_tasks=open_tasks,
    )


# ---------------------------------------------------------------------------
# Scenario 1: vendor reply with one open task → agent fires share_update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_vendor_confirmation_triggers_share_update(db_ready, monkeypatch):
    from backend.chatbot.agents.outbound import outbound_agent
    from backend.db import outbound_ledger

    biz = db_ready["business_id"]
    alice = db_ready["alice_id"]
    contact = db_ready["contact_id"]

    task_key = uuid4().hex
    await outbound_ledger.insert_task(
        task_key=task_key,
        business_id=biz,
        customer_id=alice,
        initiated_by="customer",
        dispatch_prompt="confirm Oxford 15 stock and price",
        timeout_at=datetime.now(timezone.utc) + timedelta(hours=1),
        contact_id=contact,
        contact_name="Vendor X",
        contact_role="vendor",
    )

    # Capture customer-side inbox.ingest calls so we can verify the fan-out
    # without actually waking the central agent.
    from backend.chatbot.conversations import inbox as conv_inbox

    ingest_calls: list[dict] = []
    monkeypatch.setattr(
        conv_inbox,
        "ingest",
        lambda party, item, dedup_id=None, runner=None: ingest_calls.append(
            {"party": party, "item": item, "dedup_id": dedup_id}
        ),
    )

    # Script: model issues exactly one share_update, then a final text reply.
    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        called = _all_tool_call_names(messages)
        if "share_update" not in called:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="share_update",
                        args={
                            "items": [
                                {
                                    "task_key": task_key,
                                    "relay_to_customer": (
                                        "Vendor X confirmed Oxford size 15 in stock at NGN 30,000."
                                    ),
                                }
                            ]
                        },
                    )
                ]
            )
        # Got the share_update result back — now write the final vendor-side reply.
        return ModelResponse(parts=[TextPart(content="Thanks, will let the customer know.")])

    deps = _make_deps(biz, contact, alice, await outbound_ledger.list_open_tasks_by_contact(biz, contact))

    with outbound_agent.override(model=FunctionModel(function=script)):
        result = await outbound_agent.run(
            "Got it, Oxford size 15 in stock — 30,000 NGN.", deps=deps
        )

    # Agent-side text output is what would go to the vendor.
    assert result.output == "Thanks, will let the customer know."

    # Ledger: task still open, log gained a relay section.
    row = await outbound_ledger.get_by_key(task_key)
    assert row.closed_at is None
    assert "## Relayed to customer" in row.log
    assert "30,000" in row.log

    # Hook: fired exactly one customer-side ingest with the relay text.
    assert len(ingest_calls) == 1
    payload = ingest_calls[0]["item"]["payload"]
    assert "30,000" in payload["summary"]
    assert payload["task_key"] == task_key


# ---------------------------------------------------------------------------
# Scenario 2: two open tasks, ambiguous vendor reply → find_tasks → share_update
# (The screenshot's failure mode — three triplicate share_updates avoided.)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_multi_customer_vendor_disambiguates_via_find_tasks(db_ready, monkeypatch):
    from backend.chatbot.agents.outbound import outbound_agent
    from backend.db import outbound_ledger

    biz = db_ready["business_id"]
    alice = db_ready["alice_id"]
    bob = db_ready["bob_id"]
    contact = db_ready["contact_id"]

    alice_task = uuid4().hex
    bob_task = uuid4().hex
    await outbound_ledger.insert_task(
        task_key=alice_task,
        business_id=biz,
        customer_id=alice,
        initiated_by="customer",
        dispatch_prompt="confirm Oxford 15 stock for delivery to 1 Justice Coker Estate",
        timeout_at=datetime.now(timezone.utc) + timedelta(hours=1),
        contact_id=contact,
        contact_name="Vendor X",
        contact_role="vendor",
    )
    await outbound_ledger.insert_task(
        task_key=bob_task,
        business_id=biz,
        customer_id=bob,
        initiated_by="customer",
        dispatch_prompt="check ankara fabric purple 6 yards availability",
        timeout_at=datetime.now(timezone.utc) + timedelta(hours=1),
        contact_id=contact,
        contact_name="Vendor X",
        contact_role="vendor",
    )

    from backend.chatbot.conversations import inbox as conv_inbox

    ingest_calls: list[dict] = []
    monkeypatch.setattr(
        conv_inbox,
        "ingest",
        lambda party, item, dedup_id=None, runner=None: ingest_calls.append(
            {"party": party, "item": item, "dedup_id": dedup_id}
        ),
    )

    # Script: turn 1 → find_tasks; turn 2 → share_update with the matched task; turn 3 → text.
    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        called = _all_tool_call_names(messages)
        if "find_tasks" not in called:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="find_tasks",
                        args={
                            "query": "1 Justice Coker Estate Oxford 15 delivery",
                            "contact_id": str(contact),
                        },
                    )
                ]
            )
        if "share_update" not in called:
            # Read the find_tasks return to pick the matched task_key.
            returns = _last_tool_returns(messages)
            find_results = next(
                (content for name, content in returns if name == "find_tasks"), []
            )
            assert isinstance(find_results, list) and find_results, (
                "find_tasks must return at least one row"
            )
            picked = find_results[0]["task_key"]
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="share_update",
                        args={
                            "items": [
                                {
                                    "task_key": picked,
                                    "relay_to_customer": (
                                        "Vendor confirmed delivery is going out today to "
                                        "1 Justice Coker Estate."
                                    ),
                                }
                            ]
                        },
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content="Got it, thanks.")])

    open_tasks = await outbound_ledger.list_open_tasks_by_contact(biz, contact)
    deps = _make_deps(biz, contact, customer_id=None, open_tasks=open_tasks)

    with outbound_agent.override(model=FunctionModel(function=script)):
        result = await outbound_agent.run(
            "Address noted — delivery going out today.", deps=deps
        )

    assert result.output == "Got it, thanks."

    # Alice's task got the relay; Bob's didn't.
    alice_row = await outbound_ledger.get_by_key(alice_task)
    bob_row = await outbound_ledger.get_by_key(bob_task)
    assert "## Relayed to customer" in alice_row.log
    assert "1 Justice Coker" in alice_row.log
    assert "## Relayed to customer" not in bob_row.log

    # Exactly one customer-side fan-out, addressed to Alice.
    assert len(ingest_calls) == 1
    party = ingest_calls[0]["party"]
    assert party.kind == "customer"
    assert party.party_id == str(alice)


# ---------------------------------------------------------------------------
# Scenario 3: closed-task reference → find_tasks + surface_to_customer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_closed_task_followup_routes_through_surface_to_customer(
    db_ready, monkeypatch
):
    from backend.chatbot.agents.outbound import outbound_agent
    from backend.db import outbound_ledger

    biz = db_ready["business_id"]
    alice = db_ready["alice_id"]
    contact = db_ready["contact_id"]

    closed_key = uuid4().hex
    await outbound_ledger.insert_task(
        task_key=closed_key,
        business_id=biz,
        customer_id=alice,
        initiated_by="customer",
        dispatch_prompt="arrange delivery to 1 Justice Coker for paid Oxford 15",
        timeout_at=datetime.now(timezone.utc) + timedelta(hours=1),
        contact_id=contact,
        contact_name="Vendor X",
        contact_role="vendor",
    )
    # Close it (delivered yesterday).
    await outbound_ledger.close_task(
        closed_key,
        reason="delivered + paid",
        final_log_entry="Customer received the order.",
    )

    from backend.chatbot.conversations import inbox as conv_inbox

    ingest_calls: list[dict] = []
    monkeypatch.setattr(
        conv_inbox,
        "ingest",
        lambda party, item, dedup_id=None, runner=None: ingest_calls.append(
            {"party": party, "item": item, "dedup_id": dedup_id}
        ),
    )

    # Vendor follow-up: a refund issue on the closed order. Manifest is
    # empty (only closed tasks). Agent must search → use surface_to_customer.
    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        called = _all_tool_call_names(messages)
        if "find_tasks" not in called:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="find_tasks",
                        args={"query": "Oxford 15 1 Justice Coker delivered refund"},
                    )
                ]
            )
        if "surface_to_customer" not in called:
            returns = _last_tool_returns(messages)
            results = next(
                (content for name, content in returns if name == "find_tasks"), []
            )
            assert results, "find_tasks must surface the closed task"
            picked = results[0]
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="surface_to_customer",
                        args={
                            "summary": (
                                "Heads up — Vendor X flagged a possible refund issue on "
                                "your delivered Oxford order. Looking into it."
                            ),
                            "customer_id": picked["customer_id"],
                        },
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content="Looking into it now.")])

    open_tasks = await outbound_ledger.list_open_tasks_by_contact(biz, contact)
    open_keys = {t.task_key for t in open_tasks}
    assert closed_key not in open_keys, "closed task must not appear in manifest"
    deps = _make_deps(biz, contact, customer_id=None, open_tasks=open_tasks)

    with outbound_agent.override(model=FunctionModel(function=script)):
        result = await outbound_agent.run(
            "Hey — there's a refund issue with that Oxford order from yesterday.",
            deps=deps,
        )

    assert result.output == "Looking into it now."
    # Customer-side fan-out fired with the right customer_id.
    assert len(ingest_calls) == 1
    party = ingest_calls[0]["party"]
    assert party.kind == "customer"
    assert party.party_id == str(alice)
    payload = ingest_calls[0]["item"]["payload"]
    assert "refund" in payload["summary"]
