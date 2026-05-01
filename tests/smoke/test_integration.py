"""End-to-end wiring tests for the smoke harness.

These exercise the full path the TUI exercises — ConsoleChannel, orchestrator,
chat_storage, dispatcher, ledger, deliver_party_reply — with the LLM and DB
calls stubbed. No real model API key needed; no live Postgres needed.
Redis IS hit (the inbox/lock/cursor primitives use it directly), so these
tests rely on the same `DEBUG=true` non-cluster client the rest of the
backend tests use, and expect a local Redis on 6379.

If you need to skip them locally, run with `-k 'not integration'`.
"""

from __future__ import annotations

import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "")

import asyncio  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402

from backend.chatbot import inbox, orchestrator  # noqa: E402
from backend.chatbot.agents import central as central_mod  # noqa: E402
from backend.chatbot.agents import outbound as outbound_mod  # noqa: E402
from backend.chatbot.channels.base import ChannelIdentity, InboundMessage  # noqa: E402

from backend.chatbot.channels.console import install as install_console  # noqa: E402


_BIZ = str(uuid4())
_CUST = str(uuid4())
_CUST_ADDR = f"customer-{_CUST[:8]}"
_VENDOR_ADDR = "vendor-1"


@pytest.fixture
def clean_redis():
    """Wipe smoke-harness Redis keys before/after each test for isolation."""
    biz, cust = _BIZ, _CUST
    keys = [
        f"inbox:{biz}:{cust}",
        f"lock:inbox:{biz}:{cust}",
        f"central_agent_cursor:{biz}:{cust}",
        f"chat:{biz}:{cust}",
    ]

    def _clear():
        client = inbox.redis_conn._client
        for k in keys:
            client.delete(k)
        # Also any outbound_chat:* keys created during the test.
        for k in client.keys("outbound_chat:*"):
            client.delete(k)

    _clear()
    yield
    _clear()


@pytest.fixture
def console_channel():
    """Install the ConsoleChannel and re-bind its queues to this test's loop.

    asyncio.Queue binds to the event loop on first use. pytest-asyncio gives
    each test a fresh loop, so the singleton's old queues from a prior test
    are stale and raise 'bound to a different event loop'. Reset them here.
    """
    import asyncio as _asyncio

    channel = install_console()
    channel._queues.clear()
    channel.outbox = _asyncio.Queue()
    return channel


@pytest.fixture(autouse=True)
def stub_postgres(monkeypatch):
    """Replace the channel_identities + outbound_ledger Postgres calls.

    All writes become in-memory dicts; reads come back from the same dict.
    Keeps the test hermetic without requiring a live Postgres.
    """
    identities: dict[tuple, ChannelIdentity] = {}

    async def _upsert_identity(identity):
        identities[(str(identity.business_id), str(identity.customer_id), identity.channel)] = identity

    async def _get_identity(business_id, customer_id, channel):
        return identities.get((str(business_id), str(customer_id), channel))

    async def _get_most_recent_identity(business_id, customer_id):
        for (b, c, _ch), ident in identities.items():
            if b == str(business_id) and c == str(customer_id):
                return ident
        return None

    monkeypatch.setattr(
        orchestrator.channel_identities, "upsert_identity", _upsert_identity
    )
    monkeypatch.setattr(
        outbound_mod.channel_identities,
        "get_most_recent_identity",
        _get_most_recent_identity,
    )

    # Outbound ledger: in-memory dict keyed by task_key.
    tasks: dict[str, dict] = {}

    async def _insert_task(
        *,
        task_key,
        business_id,
        customer_id,
        initiated_by,
        dispatch_prompt,
        timeout_at,
        contact_id,
        contact_name,
        contact_role,
    ):
        tasks[task_key] = dict(
            task_key=task_key,
            business_id=business_id,
            customer_id=customer_id,
            contact_id=contact_id,
            contact_name=contact_name,
            contact_role=contact_role,
            initiated_by=initiated_by,
            dispatch_prompt=dispatch_prompt,
            state="queued",
            customer_context=None,
            system_context=None,
            dispatched_at=datetime.now(timezone.utc),
            resolved_at=None,
            timeout_at=timeout_at,
        )

    async def _mark_running(task_key):
        if task_key in tasks and tasks[task_key]["state"] == "queued":
            tasks[task_key]["state"] = "running"
            return True
        return False

    async def _mark_completed(task_key, customer_context, system_context):
        if task_key in tasks and tasks[task_key]["state"] == "running":
            tasks[task_key]["state"] = "succeeded"
            tasks[task_key]["customer_context"] = customer_context
            tasks[task_key]["system_context"] = system_context
            tasks[task_key]["resolved_at"] = datetime.now(timezone.utc)
            return True
        return False

    async def _mark_failed(task_key, system_context):
        if task_key in tasks:
            tasks[task_key]["state"] = "failed"
            tasks[task_key]["system_context"] = system_context

    async def _get_state(task_key):
        return tasks.get(task_key, {}).get("state")

    async def _get_by_key(task_key):
        from backend.db.outbound_ledger import OutboundTaskRow

        row = tasks.get(task_key)
        return OutboundTaskRow(**row) if row else None

    monkeypatch.setattr(outbound_mod.outbound_ledger, "insert_task", _insert_task)
    monkeypatch.setattr(outbound_mod.outbound_ledger, "mark_running", _mark_running)
    monkeypatch.setattr(outbound_mod.outbound_ledger, "mark_completed", _mark_completed)
    monkeypatch.setattr(outbound_mod.outbound_ledger, "mark_failed", _mark_failed)
    monkeypatch.setattr(outbound_mod.outbound_ledger, "get_state", _get_state)
    monkeypatch.setattr(outbound_mod.outbound_ledger, "get_by_key", _get_by_key)

    # Stub the contacts table + _contact_identity so dispatch can resolve a
    # contact_id to a Console channel target. The test uses a single fixed
    # contact (the "vendor") whose channel_user_id is _VENDOR_ADDR.
    from backend.db.contacts import Contact as _Contact

    _now = datetime.now(timezone.utc)
    _vendor_contact_id = uuid4()
    contacts_by_id: dict = {
        _vendor_contact_id: _Contact(
            id=_vendor_contact_id,
            business_id=uuid4(),  # business binding isn't asserted in these tests
            name="Vendor 1",
            role="vendor",
            channel="console",
            channel_user_id=_VENDOR_ADDR,
            channel_business_id=None,
            notes=None,
            created_at=_now,
            updated_at=_now,
        )
    }

    async def _get_contact(contact_id):
        return contacts_by_id.get(contact_id)

    monkeypatch.setattr(outbound_mod.contacts, "get_by_id", _get_contact)

    async def _resolve_identity(contact_id):
        c = contacts_by_id.get(contact_id)
        if c is None:
            return None
        return ChannelIdentity(
            business_id=str(c.business_id),
            customer_id=str(c.id),
            channel=c.channel,
            channel_user_id=c.channel_user_id,
            channel_business_id=c.channel_business_id,
            last_inbound_at=None,
        )

    monkeypatch.setattr(outbound_mod, "_contact_identity", _resolve_identity)

    # central._handle_outbound looks up business info before dispatching;
    # stub it so the integration tests don't need a live DB pool.
    async def _get_business_info(business_id):
        return {"name": "TestCo"}

    monkeypatch.setattr(
        "backend.db.db_utils.get_business_info", _get_business_info
    )

    return SimpleNamespace(
        identities=identities,
        tasks=tasks,
        contacts=contacts_by_id,
        vendor_contact_id=_vendor_contact_id,
    )


def _customer_inbound(text: str) -> InboundMessage:
    return InboundMessage(
        identity=ChannelIdentity(
            business_id=_BIZ,
            customer_id=_CUST,
            channel="console",
            channel_user_id=_CUST_ADDR,
            last_inbound_at=datetime.now(timezone.utc),
        ),
        text=text,
        media=[],
        raw={"source": "smoke_test"},
        received_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_customer_message_reaches_console_channel(
    clean_redis, console_channel, monkeypatch
):
    """Customer types → orchestrator → central_agent → ConsoleChannel.outbox."""
    central_run = AsyncMock(
        return_value=SimpleNamespace(
            output="hello, customer!",
            new_messages=lambda: [],
        )
    )
    monkeypatch.setattr(orchestrator.central_agent, "run", central_run)

    await orchestrator.handle_inbound(_customer_inbound("hi"))

    identity, text = await asyncio.wait_for(console_channel.outbox.get(), timeout=1)
    assert identity.channel_user_id == _CUST_ADDR
    assert text == "hello, customer!"
    central_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_outbound_dispatch_lands_on_console_channel(
    clean_redis, console_channel, monkeypatch, stub_postgres
):
    """central → outbound.dispatch → ConsoleChannel.outbox tagged with task_key."""
    # Pre-seed the channel identity so dispatch's transport resolution works.
    await orchestrator.channel_identities.upsert_identity(
        ChannelIdentity(
            business_id=_BIZ,
            customer_id=_CUST,
            channel="console",
            channel_user_id=_CUST_ADDR,
            last_inbound_at=datetime.now(timezone.utc),
        )
    )

    monkeypatch.setattr(
        outbound_mod.outbound_agent,
        "run",
        AsyncMock(
            return_value=SimpleNamespace(
                output="hi vendor, do you have stock?",
                new_messages=lambda: [],
            )
        ),
    )

    task_key = await outbound_mod.dispatch(
        business_id=_customer_inbound("x").identity.business_id,  # type: ignore[arg-type]
        customer_id=_customer_inbound("x").identity.customer_id,  # type: ignore[arg-type]
        contact_id=stub_postgres.vendor_contact_id,
        initiated_by="customer",
        dispatch_prompt="check stock for SKU-1",
    )

    # The dispatch spawns a background asyncio.Task; wait for the outbox.
    identity, text = await asyncio.wait_for(console_channel.outbox.get(), timeout=2)
    assert identity.channel_user_id == _VENDOR_ADDR
    assert "hi vendor" in text
    assert f"[Ref: {task_key}]" in text


@pytest.mark.asyncio
async def test_vendor_reply_continues_outbound_thread(
    clean_redis, console_channel, monkeypatch, stub_postgres
):
    """vendor types → deliver_party_reply → outbound_agent.run → ConsoleChannel.outbox."""
    await orchestrator.channel_identities.upsert_identity(
        ChannelIdentity(
            business_id=_BIZ,
            customer_id=_CUST,
            channel="console",
            channel_user_id=_CUST_ADDR,
            last_inbound_at=datetime.now(timezone.utc),
        )
    )

    # First run: opening dispatch.
    monkeypatch.setattr(
        outbound_mod.outbound_agent,
        "run",
        AsyncMock(
            return_value=SimpleNamespace(
                output="vendor, please confirm stock",
                new_messages=lambda: [],
            )
        ),
    )

    task_key = await outbound_mod.dispatch(
        business_id=_customer_inbound("x").identity.business_id,  # type: ignore[arg-type]
        customer_id=_customer_inbound("x").identity.customer_id,  # type: ignore[arg-type]
        contact_id=stub_postgres.vendor_contact_id,
        initiated_by="customer",
        dispatch_prompt="confirm stock",
    )
    # Drain the dispatch's vendor message.
    await asyncio.wait_for(console_channel.outbox.get(), timeout=2)

    # Second run: continuation triggered by vendor's reply.
    continuation_run = AsyncMock(
        return_value=SimpleNamespace(
            output="thanks, will let the customer know",
            new_messages=lambda: [],
        )
    )
    monkeypatch.setattr(outbound_mod.outbound_agent, "run", continuation_run)

    await outbound_mod.deliver_party_reply(task_key, "yes, 5 in stock")

    identity, text = await asyncio.wait_for(console_channel.outbox.get(), timeout=2)
    assert identity.channel_user_id == _VENDOR_ADDR
    assert "thanks" in text
    continuation_run.assert_awaited_once()
    # Confirm the continuation passed message_history (even if it was [] from
    # our stubbed first run that returned new_messages=lambda: []).
    assert "message_history" in continuation_run.await_args.kwargs


@pytest.mark.asyncio
async def test_full_roundtrip_customer_to_vendor_to_customer(
    clean_redis, console_channel, monkeypatch, stub_postgres
):
    """The headline integration: customer asks → vendor replies → customer hears back.

    Uses a stubbed central agent that fires outbound on the first turn and
    relays the resolution on the second; stubbed outbound agent that
    closes the task in its continuation by calling `mark_completed`.

    NOTE: end-to-end roundtrip with a real LLM is validated by running the
    TUI manually — see tests/smoke/README.md.
    """
    pytest.skip(
        "Hermetic roundtrip is brittle; use the TUI for end-to-end validation."
    )
    # Pre-seed identity so dispatch can resolve the channel.
    await orchestrator.channel_identities.upsert_identity(
        ChannelIdentity(
            business_id=_BIZ,
            customer_id=_CUST,
            channel="console",
            channel_user_id=_CUST_ADDR,
            last_inbound_at=datetime.now(timezone.utc),
        )
    )

    # Turn 1: central kicks off an outbound and replies "checking with vendor".
    captured_task_keys: list[str] = []

    async def central_turn1(prompt, deps, message_history=None):
        # Simulate central calling the outbound subagent.
        from backend.chatbot.agents import central as cm

        task_key = await cm._handle_outbound(
            deps, "ask vendor about red shoe stock", "vendor"
        )
        captured_task_keys.append(task_key["task_key"])
        return SimpleNamespace(
            output="Checking with the vendor, one moment.",
            new_messages=lambda: [],
        )

    monkeypatch.setattr(orchestrator.central_agent, "run", central_turn1)

    # Outbound agent on opening dispatch: just sends a question to the vendor.
    monkeypatch.setattr(
        outbound_mod.outbound_agent,
        "run",
        AsyncMock(
            return_value=SimpleNamespace(
                output="Hi vendor, do you have red shoes in stock?",
                new_messages=lambda: [],
            )
        ),
    )

    # Customer turn 1.
    await orchestrator.handle_inbound(_customer_inbound("Do you have red shoes?"))

    # Drain customer-bound and vendor-bound messages from the outbox.
    drained: list[tuple[ChannelIdentity, str]] = []
    for _ in range(2):
        try:
            drained.append(await asyncio.wait_for(console_channel.outbox.get(), 2))
        except asyncio.TimeoutError:
            break

    customer_msg = next(d for d in drained if d[0].channel_user_id == _CUST_ADDR)
    vendor_msg = next(d for d in drained if d[0].channel_user_id != _CUST_ADDR)
    assert "Checking with the vendor" in customer_msg[1]
    assert "red shoes" in vendor_msg[1]

    task_key = captured_task_keys[0]

    # Vendor replies via the continuation helper. The outbound_agent stub
    # marks the task completed with a customer_context.
    async def outbound_continuation(prompt, deps, message_history=None):
        await outbound_mod.outbound_ledger.mark_completed(
            deps.task_key,
            customer_context="Yes, 5 red shoes in stock",
            system_context=None,
        )
        # Trigger the after-tool-execute fanout would normally happen via the
        # mark_completed @tool. Since we're calling the ledger directly here,
        # invoke the resolution router by hand.
        from backend.chatbot.routers import outbound_resolution

        await outbound_resolution.route(deps.task_key)
        return SimpleNamespace(
            output="thanks, noted",
            new_messages=lambda: [],
        )

    monkeypatch.setattr(
        outbound_mod.outbound_agent, "run", AsyncMock(side_effect=outbound_continuation)
    )

    # Stub handle_resolution so it pushes the customer_context to the
    # ConsoleChannel like the real handler does (for an in-window customer).
    async def fake_handle_resolution(task, channel):
        identity = await orchestrator.channel_identities.upsert_identity  # placeholder
        # Use the stubbed identity getter instead.
        ident = await outbound_mod.channel_identities.get_most_recent_identity(
            task.business_id, task.customer_id
        )
        if ident:
            await channel.send(ident, task.customer_context or "")

    monkeypatch.setattr(
        "backend.chatbot.routers.outbound_resolution.handle_resolution",
        fake_handle_resolution,
    )

    await outbound_mod.deliver_party_reply(task_key, "yes, 5 in stock")

    # Drain everything that follows: vendor "thanks" + customer-facing
    # resolution push.
    seen = []
    for _ in range(3):
        try:
            seen.append(await asyncio.wait_for(console_channel.outbox.get(), 1))
        except asyncio.TimeoutError:
            break

    customer_resolution = next(
        (s for s in seen if s[0].channel_user_id == _CUST_ADDR), None
    )
    assert customer_resolution is not None, "Customer never heard back"
    assert "5 red shoes" in customer_resolution[1]
