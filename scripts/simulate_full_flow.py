"""End-to-end live simulation of the unified-inbox architecture.

Drives the REAL central + outbound agents (no mocks) through a scripted
scenario covering both Conversation paths and the after_tool_execute hook.
The only simulated piece is the transport: a RecordingChannel captures
every outbound message instead of dispatching to WhatsApp.

Run: `cd app && python3 ../scripts/simulate_full_flow.py`

Prereqs: Postgres + Redis up (docker compose); MODEL_NAME + matching
provider API key in env (LLM calls cost real money). Migrations must be
applied — run `python -m cli.cli --scenario healthcheck` once first.

Scenes: (1) customer kickoff → outbound dispatch, (2) vendor burst within
debounce → single coalesced drain, (3) hook ingests system_event into
customer inbox, (4) customer debounce → central runs with system_event,
(5) duplicate dedup_id is dropped.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

# Prepend app/ so `from backend.*` resolves regardless of cwd.
_APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_APP_DIR / ".env")

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("LOGFIRE_IGNORE_NO_CONFIG", "1")


# ---------------------------------------------------------------------------
# Recording channel — captures sends instead of dispatching to WhatsApp.
# ---------------------------------------------------------------------------


from backend.chatbot.channels import registry as channel_registry  # noqa: E402
from backend.chatbot.channels.base import (  # noqa: E402
    Channel,
    ChannelIdentity,
    InboundMessage,
    WindowPolicy,
)


class RecordingChannel(Channel):
    """Stand-in for whatsapp/console — captures every send into a list."""

    name = "whatsapp"  # Hijack the whatsapp slot so contacts (channel='whatsapp') resolve here.

    def __init__(self) -> None:
        self.sent: list[tuple[ChannelIdentity, str]] = []

    def parse_inbound(self, raw: dict) -> InboundMessage:
        raise NotImplementedError("RecordingChannel doesn't parse webhooks")

    async def send(self, identity: ChannelIdentity, text: str) -> None:
        self.sent.append((identity, text))
        _log_send(identity, text)

    async def send_template(
        self, identity: ChannelIdentity, template: str, vars: dict
    ) -> None:
        rendered = f"[template:{template}] {vars}"
        self.sent.append((identity, rendered))
        _log_send(identity, rendered)

    def window_policy(self) -> WindowPolicy:
        return WindowPolicy(
            has_window=False, window_hours=None, out_of_window_behavior="drop"
        )


def _log_send(identity: ChannelIdentity, text: str) -> None:
    role = "vendor" if identity.channel_user_id.startswith("vendor-") else "customer"
    print(f"  [send→{role}] {text!r}")


# ---------------------------------------------------------------------------
# Instrumentation — wrap inbox.ingest and Conversation.drain.
# ---------------------------------------------------------------------------


from backend.chatbot.conversations import inbox as conv_inbox  # noqa: E402
from backend.chatbot.conversations.inbox import PartyKey  # noqa: E402

_INGEST_LOG: list[dict[str, Any]] = []
_DRAIN_LOG: list[dict[str, Any]] = []
_orig_ingest = conv_inbox.ingest


def _wrap_ingest():
    def wrapped(party, item, *, dedup_id, runner):
        result = _orig_ingest(party, item, dedup_id=dedup_id, runner=runner)
        entry = {
            "party": party,
            "type": item.get("type"),
            "dedup_id": dedup_id,
            "enqueued": result,
        }
        _INGEST_LOG.append(entry)
        print(
            f"  [ingest] party={party.kind}:{party.party_id[:8]} "
            f"type={entry['type']} dedup={dedup_id} enqueued={result}"
        )
        return result

    conv_inbox.ingest = wrapped


def _wrap_drain():
    from backend.chatbot.conversations import conversation as conv_mod

    orig = conv_mod.Conversation.drain

    async def wrapped(self, party, items):
        print(
            f"  [drain start] party={party.kind}:{party.party_id[:8]} "
            f"items={len(items)} types={[i.get('type') for i in items]}"
        )
        _DRAIN_LOG.append({"party": party, "items": list(items)})
        try:
            await orig(self, party, items)
        except Exception as exc:
            print(f"  [drain raised] {type(exc).__name__}: {exc}")
            raise
        finally:
            print(f"  [drain finish] party={party.kind}:{party.party_id[:8]}")

    conv_mod.Conversation.drain = wrapped


# ---------------------------------------------------------------------------
# Setup helpers — seed business + customer + vendor contact + product.
# ---------------------------------------------------------------------------


async def _seed(business_id: UUID, customer_id: UUID, vendor_wa_id: str) -> UUID:
    from backend.db import contacts
    from backend.db.connection import get_db
    from cli.seed import ensure_smoke_data, reset_smoke_state

    await reset_smoke_state(str(business_id), str(customer_id))
    await ensure_smoke_data(str(business_id), str(customer_id))

    # Add a fabric product so the customer's question has something to bind to.
    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO products (business_id, name, description, price,
                                  stock_quantity, sku, category)
            SELECT $1, $2, $3, $4, $5, $6, $7
            WHERE NOT EXISTS (
                SELECT 1 FROM products WHERE business_id=$1 AND sku=$6
            )
            """,
            business_id,
            "Red Ankara Fabric",
            "Premium red ankara, sold per yard.",
            2200,
            0,  # out of stock — forces vendor outreach
            "ANK-RED-001",
            "fabric",
        )
        # Make sure the business has a whatsapp_phone_number_id so the
        # outbound side can resolve a sender phone id.
        await conn.execute(
            "UPDATE businesses SET whatsapp_phone_number_id = $2 WHERE id = $1",
            business_id,
            "phone-numbers-fake-1",
        )

    contact = await contacts.upsert(
        business_id=business_id,
        name="Mama Adunni",
        role="vendor",
        channel="whatsapp",
        channel_user_id=vendor_wa_id,
        channel_business_id="phone-numbers-fake-1",
        notes="Ankara fabrics supplier in Balogun market.",
    )
    return contact.id


async def _seed_customer_identity(
    business_id: UUID, customer_id: UUID, customer_wa_id: str
) -> None:
    from backend.db import channel_identities

    await channel_identities.upsert_identity(
        ChannelIdentity(
            business_id=str(business_id),
            customer_id=str(customer_id),
            channel="whatsapp",
            channel_user_id=customer_wa_id,
            channel_business_id="phone-numbers-fake-1",
            last_inbound_at=datetime.now(timezone.utc),
        )
    )


# ---------------------------------------------------------------------------
# Assertions tracker.
# ---------------------------------------------------------------------------


_RESULTS: list[tuple[str, bool, str]] = []


def _assert(name: str, ok: bool, detail: str = "") -> None:
    _RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Scenes.
# ---------------------------------------------------------------------------


async def _scene_1_customer_kickoff(
    channel: RecordingChannel,
    business_id: UUID,
    customer_id: UUID,
):
    from backend.chatbot.conversations.registry import customer_conversation
    from backend.db import outbound_ledger

    print("\n=== SCENE 1: customer kicks off vendor outreach ===")

    biz = str(business_id)
    cust = str(customer_id)
    convo = customer_conversation(biz, cust)
    text = "Do you have the red ankara fabric in stock? Need 5 yards."
    print(f"  > [customer] {text!r}")

    conv_inbox.ingest(
        PartyKey.customer(biz, cust),
        conv_inbox.make_user_message_item(text=text, dedup_id="msg1"),
        dedup_id="msg1",
        runner=convo.drain,
    )

    # Wait past debounce + agent run. dispatch() spawns a background task; we
    # wait for an outbound_tasks ledger row to materialize.
    print("  ... waiting for debounce (10s) + central+outbound runs (~60s)")
    deadline = asyncio.get_event_loop().time() + 90
    pending: list = []
    while asyncio.get_event_loop().time() < deadline:
        pending = await outbound_ledger.get_pending_for_customer(
            business_id, customer_id
        )
        if pending:
            break
        await asyncio.sleep(1.0)

    _assert("scene1.outbound_task_created", bool(pending),
            f"open tasks={len(pending)}")
    if not pending:
        return None

    task = pending[0]
    # Wait for the dispatch to actually send to the vendor.
    deadline = asyncio.get_event_loop().time() + 60
    vendor_msgs: list[tuple[ChannelIdentity, str]] = []
    while asyncio.get_event_loop().time() < deadline:
        vendor_msgs = [
            (i, t) for i, t in channel.sent
            if i.channel_user_id.startswith("vendor-")
        ]
        if vendor_msgs:
            break
        await asyncio.sleep(1.0)

    _assert("scene1.vendor_received_dispatch", bool(vendor_msgs),
            f"sent to vendor={len(vendor_msgs)}")
    customer_msgs = [
        (i, t) for i, t in channel.sent
        if not i.channel_user_id.startswith("vendor-")
    ]
    _assert("scene1.customer_got_interim_reply", bool(customer_msgs),
            f"sent to customer={len(customer_msgs)}")
    return task


async def _scene_2_vendor_burst(
    channel: RecordingChannel,
    business_id: UUID,
    contact_id: UUID,
    initial_send_count: int,
):
    from backend.chatbot.conversations.registry import vendor_conversation

    print("\n=== SCENE 2: vendor sends burst within debounce window ===")

    biz = str(business_id)
    cid = str(contact_id)
    convo = vendor_conversation(biz, cid)

    drain_count_before = sum(
        1 for d in _DRAIN_LOG if d["party"].kind == "vendor"
    )

    msgs = ["yes", "we have 8 yards", "₦2500 per yard"]
    for i, text in enumerate(msgs):
        print(f"  > [vendor] {text!r}")
        conv_inbox.ingest(
            PartyKey.vendor(biz, cid),
            conv_inbox.make_user_message_item(
                text=text, dedup_id=f"vendor-msg-{i}"
            ),
            dedup_id=f"vendor-msg-{i}",
            runner=convo.drain,
        )
        await asyncio.sleep(1.5)  # well inside the 10s window

    # Wait for one drain to fire and complete (debounce + agent run).
    print("  ... waiting for debounce + outbound run (~90s)")
    deadline = asyncio.get_event_loop().time() + 90
    while asyncio.get_event_loop().time() < deadline:
        new_drains = [
            d for d in _DRAIN_LOG[drain_count_before:]
            if d["party"].kind == "vendor"
        ]
        if new_drains and len(channel.sent) > initial_send_count:
            # Drain ran AND sent (ensures agent.run completed)
            await asyncio.sleep(2.0)  # let any straggler finish
            break
        await asyncio.sleep(1.0)

    new_vendor_drains = [
        d for d in _DRAIN_LOG[drain_count_before:] if d["party"].kind == "vendor"
    ]
    _assert(
        "scene2.single_drain_for_three_messages",
        len(new_vendor_drains) == 1,
        f"drains={len(new_vendor_drains)}",
    )
    if new_vendor_drains:
        items = new_vendor_drains[0]["items"]
        _assert(
            "scene2.three_messages_coalesced",
            len(items) == 3,
            f"items in drain={len(items)}",
        )


async def _scene_3_hook_fired(business_id: UUID, customer_id: UUID):
    print("\n=== SCENE 3: after_tool_execute hook fires ===")

    # Look at ingest log for system_event into customer inbox with dedup
    # prefix "resolve:".
    customer_party = PartyKey.customer(str(business_id), str(customer_id))
    resolve_ingests = [
        e for e in _INGEST_LOG
        if e["party"] == customer_party
        and e["type"] == "system_event"
        and (e["dedup_id"] or "").startswith("resolve:")
    ]
    _assert(
        "scene3.system_event_in_customer_inbox",
        bool(resolve_ingests),
        f"resolve ingests={len(resolve_ingests)}",
    )
    if resolve_ingests:
        _assert(
            "scene3.dedup_key_prefixed_resolve",
            (resolve_ingests[0]["dedup_id"] or "").startswith("resolve:"),
            resolve_ingests[0]["dedup_id"] or "",
        )


async def _scene_4_customer_final(
    channel: RecordingChannel, business_id: UUID, customer_id: UUID
):
    print("\n=== SCENE 4: customer inbox debounces, central runs ===")

    customer_party = PartyKey.customer(str(business_id), str(customer_id))
    drain_count_before = sum(
        1 for d in _DRAIN_LOG if d["party"] == customer_party
    )
    sends_before = len(
        [s for s in channel.sent if not s[0].channel_user_id.startswith("vendor-")]
    )

    print("  ... waiting for customer drain (~70s)")
    deadline = asyncio.get_event_loop().time() + 70
    while asyncio.get_event_loop().time() < deadline:
        new = [
            d for d in _DRAIN_LOG[drain_count_before:]
            if d["party"] == customer_party
        ]
        new_sends = [
            s for s in channel.sent
            if not s[0].channel_user_id.startswith("vendor-")
        ]
        if new and len(new_sends) > sends_before:
            await asyncio.sleep(2.0)
            break
        await asyncio.sleep(1.0)

    new_drains = [
        d for d in _DRAIN_LOG[drain_count_before:]
        if d["party"] == customer_party
    ]
    _assert(
        "scene4.central_drained_with_system_event",
        bool(new_drains)
        and any(
            i.get("type") == "system_event"
            for d in new_drains for i in d["items"]
        ),
        f"central drains={len(new_drains)}",
    )

    customer_msgs = [
        t for i, t in channel.sent
        if not i.channel_user_id.startswith("vendor-")
    ]
    final_reply = customer_msgs[-1] if customer_msgs else ""
    print(f"  [final reply to customer] {final_reply!r}")
    text_l = final_reply.lower()
    _assert(
        "scene4.final_reply_mentions_stock_or_price",
        any(tok in text_l for tok in ("8", "yard", "2500", "₦", "price", "stock")),
        f"reply={final_reply[:120]!r}",
    )


async def _scene_5_idempotency(business_id: UUID, customer_id: UUID):
    from backend.chatbot.conversations.registry import customer_conversation

    print("\n=== SCENE 5: idempotency check on dedup_id='msg1' ===")

    biz = str(business_id)
    cust = str(customer_id)
    convo = customer_conversation(biz, cust)
    ingest_count_before = len(_INGEST_LOG)
    result = conv_inbox.ingest(
        PartyKey.customer(biz, cust),
        conv_inbox.make_user_message_item(text="redeliver", dedup_id="msg1"),
        dedup_id="msg1",
        runner=convo.drain,
    )
    last = _INGEST_LOG[-1] if len(_INGEST_LOG) > ingest_count_before else None
    _assert("scene5.dedup_returned_false", result is False, f"got {result}")
    _assert(
        "scene5.dedup_logged_as_dropped",
        bool(last) and last["enqueued"] is False,
        str(last),
    )


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------


async def main() -> int:
    logging.basicConfig(level=logging.WARNING)

    from backend.config import MODEL_NAME
    from backend.db.connection import close_db, init_db

    print(f"Model: {MODEL_NAME}")
    if not any(
        os.getenv(k) for k in (
            "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
            "ANTHROPIC_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY",
        )
    ):
        print("ERROR: no model provider key in env. Set one and re-run.")
        return 2

    await init_db()
    print("Postgres pool ready.")

    # Install RecordingChannel under the 'whatsapp' name so contacts and
    # customer identities (channel='whatsapp') resolve to it.
    channel = RecordingChannel()
    channel_registry.register(channel)

    async def _resolve_for_customer(business_id: str, customer_id: str):
        return channel
    channel_registry.set_identity_resolver(_resolve_for_customer)
    print("RecordingChannel registered as 'whatsapp'.")

    _wrap_ingest()
    _wrap_drain()

    business_id = UUID("11111111-1111-1111-1111-111111111111")
    customer_id = UUID("22222222-2222-2222-2222-222222222222")
    vendor_wa_id = f"vendor-{uuid4().hex[:8]}"
    customer_wa_id = f"customer-{str(customer_id)[:8]}"

    try:
        contact_id = await _seed(business_id, customer_id, vendor_wa_id)
        await _seed_customer_identity(business_id, customer_id, customer_wa_id)
        print(f"Seeded business={business_id} customer={customer_id} contact={contact_id}")

        sends_before_scene2 = 0  # will set after scene 1
        task = await _scene_1_customer_kickoff(channel, business_id, customer_id)
        if task is None:
            print("\nABORT — Scene 1 produced no outbound task.")
        else:
            sends_before_scene2 = len(channel.sent)
            await _scene_2_vendor_burst(
                channel, business_id, contact_id, sends_before_scene2
            )
            await _scene_3_hook_fired(business_id, customer_id)
            await _scene_4_customer_final(channel, business_id, customer_id)
        await _scene_5_idempotency(business_id, customer_id)

    finally:
        await close_db()

    print("\n=== SUMMARY ===")
    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    total = len(_RESULTS)
    for name, ok, detail in _RESULTS:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    overall = "SUCCESS" if passed == total and total > 0 else "FAILED"
    print(f"\n{overall}: {passed}/{total} assertions passed")
    return 0 if overall == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
