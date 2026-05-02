# Unified Inbox Refactor — Shared Design Brief

**This is the canonical contract for the in-flight refactor.** All implementing agents read this first and conform to the signatures here. Discussion of *why* is in `ARCHITECTURE_BRIEF.md`; this document is the *what* and *how*.

Branch: `march-refactor`. Working dir: `/Users/davidokpare/Playbook/autobiz/app/backend`. Python imports start `backend.…`.

---

## Goal

Collapse the asymmetric customer/vendor pipelines into one primitive. Today there are two inboxes (`inbox.py`, `contact_inbox.py`), two drain pipelines (`orchestrator._drain_and_reply`, `outbound.deliver_contact_reply`), and a separate resolution router (`outbound_resolution.route`). Unify them.

After this refactor:

- One inbox primitive (`backend/chatbot/conversations/inbox.py`)
- One drain pipeline (`Conversation.drain` in `backend/chatbot/conversations/conversation.py`)
- Two `Conversation` factories (`customer_conversation`, `vendor_conversation`) in `backend/chatbot/conversations/registry.py`
- 10s debounce window for both customer and vendor
- Idempotency on Meta webhook retries (dedup by message id)
- Drain only what was peeked (atomicity bug fix)
- Coordinator tools live on `outbound_agent`; `coordinator.py` deleted
- `orchestrator.py`, `inbox.py`, `contact_inbox.py`, `outbound_resolution.py` deleted

---

## File map

```
backend/chatbot/
├── _redis_queue.py             # MODIFIED — add 3 primitives (Step 1)
├── conversations/              # NEW
│   ├── __init__.py
│   ├── inbox.py                # NEW — unified queue + debounce + dedup
│   ├── conversation.py         # NEW — Conversation dataclass + drain pipeline
│   └── registry.py             # NEW — customer/vendor factories
├── agents/
│   ├── outbound.py             # MODIFIED — coordinator tools merged in; hook calls inbox.ingest directly
│   ├── central.py              # UNCHANGED
│   ├── coordinator.py          # DELETED
│   ├── deps.py                 # UNCHANGED
│   └── ...                     # UNCHANGED
├── routers/
│   └── outbound_resolution.py  # DELETED
├── inbox.py                    # DELETED
├── contact_inbox.py            # DELETED
└── orchestrator.py             # DELETED

backend/api/routers/webhooks/
├── whatsapp.py                 # MODIFIED — calls inbox.ingest with right Conversation
└── http.py                     # MODIFIED — calls inbox.ingest with customer Conversation
```

---

## Step 1 — Redis primitives (in `backend/chatbot/_redis_queue.py`)

Add these three functions. Do not modify or remove existing functions.

```python
def set_if_absent(key: str, value: str, ttl_seconds: int) -> bool:
    """SET NX with TTL. Returns True if the key was set, False if it already existed.

    Used as the dedup primitive: ingest() calls set_if_absent(dedup_key, "1", ttl)
    and drops the message if it returns False (Meta retry of a message we already
    enqueued).
    """
    return bool(redis_conn._client.set(key, value, nx=True, ex=ttl_seconds))


def peek_with_tokens(key: str) -> list[tuple[str, Any]]:
    """Return [(raw_json, parsed_dict), ...] without modifying the list.

    The raw_json string is the exact bytes stored in Redis — pass it back to
    drain_specific to LREM that exact entry. Parsed dict is the JSON-decoded
    form for application use. Corrupt entries are skipped silently (parity with
    peek()).
    """
    raw = redis_conn._client.lrange(key, 0, -1)
    out: list[tuple[str, Any]] = []
    for item in raw:
        token = item.decode() if isinstance(item, bytes) else item
        try:
            parsed = json.loads(token)
        except (ValueError, TypeError):
            continue
        out.append((token, parsed))
    return out


def drain_specific(key: str, raw_tokens: list[str]) -> int:
    """Remove specified entries from the list by exact-string match.

    Calls LREM count=1 for each token. Returns total entries removed. Items
    pushed during the agent run survive (they weren't in raw_tokens).
    """
    if not raw_tokens:
        return 0
    client = redis_conn._client
    pipe = client.pipeline(transaction=False)
    for token in raw_tokens:
        pipe.lrem(key, 1, token)
    results = pipe.execute()
    return sum(int(r or 0) for r in results)
```

Notes:
- The redis client may be configured with `decode_responses=True` (returns `str`) or `False` (returns `bytes`). The `peek_with_tokens` decode handles both, mirroring the `release_lock` pattern at `_redis_queue.py:99-102`.
- `peek` (existing) stays untouched — callers that don't need tokens use it.
- No tests for this file required (covered indirectly via inbox tests).

---

## Step 2 — `backend/chatbot/conversations/inbox.py`

The unified queue + debounce + dedup primitive. Replaces both old `inbox.py` and `contact_inbox.py`.

```python
"""Unified per-party inbox: queue + debounced drain + idempotency.

One module for both customer-side and vendor-side conversations. Each party
(customer or vendor) has:
- A Redis list of items (`{type, payload, enqueued_at, dedup_key}`)
- A per-party Redis mutex for serializing drains
- A 10s debounce window: bursts coalesce into one drain
- A dedup key on each ingest: Meta webhook retries are absorbed silently

Lifecycle:
1. `ingest(party, item, *, dedup_id, runner)` — webhooks and the after_tool_execute
   hook call this. Returns False if the dedup_id was seen in the last 24h.
2. After ingest, a single drain task is scheduled for the party. Subsequent
   ingests inside the 10s window do not schedule additional drains
   (deduped via in-process SCHEDULED_DRAINS set).
3. When the timer fires, the drain task acquires the per-party lock, peeks all
   items, calls `runner(party, items)`, and on success drains exactly those
   items (LREM by token). Items that arrived during the run survive.
4. If a drain was requested while another was running (PENDING_REDRAIN), the
   active drain re-loops instead of releasing.
5. After release, any items still queued schedule a fresh drain.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Literal
from uuid import uuid4

from backend.chatbot import _redis_queue

logger = logging.getLogger(__name__)

DRAIN_WINDOW_SECONDS = 10
INBOX_TTL_SECONDS = 24 * 60 * 60
LOCK_TTL_SECONDS = 60
DEDUP_TTL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class PartyKey:
    """Identifies one conversation participant. business_id + party_id are strings.

    `kind` exists so customer and vendor namespaces don't collide if the same UUID
    is reused across roles (extremely unlikely but cheap to guard against).
    """
    kind: Literal["customer", "vendor"]
    business_id: str
    party_id: str

    @classmethod
    def customer(cls, business_id: str, customer_id: str) -> "PartyKey":
        return cls("customer", str(business_id), str(customer_id))

    @classmethod
    def vendor(cls, business_id: str, contact_id: str) -> "PartyKey":
        return cls("vendor", str(business_id), str(contact_id))


# Runner: called by the drain task with all peeked items.
# Raises on transient failure → items remain queued, drain reschedules later.
DrainRunner = Callable[[PartyKey, list[dict]], Awaitable[None]]


def _inbox_key(p: PartyKey) -> str:
    return f"inbox:{p.kind}:{p.business_id}:{p.party_id}"


def _lock_key(p: PartyKey) -> str:
    return f"lock:inbox:{p.kind}:{p.business_id}:{p.party_id}"


def _dedup_key(dedup_id: str) -> str:
    return f"inbox:dedup:{dedup_id}"


# In-process. Acceptable: single-instance deployment. Two replicas would each
# schedule a drain; the Redis lock still serializes, the second drain peeks
# empty and exits. Same semantics as the old contact_inbox module.
_SCHEDULED_DRAINS: set[PartyKey] = set()
_PENDING_REDRAIN: set[PartyKey] = set()


def ingest(
    party: PartyKey,
    item: dict,
    *,
    dedup_id: str | None,
    runner: DrainRunner,
) -> bool:
    """Enqueue `item` and ensure a drain is scheduled. Returns False on duplicate.

    `item` shape (enforced by convention, not type):
        {"type": "user_message" | "system_event",
         "payload": {...},
         "enqueued_at": <iso str>,
         "dedup_key": <str | None>}

    `dedup_id` is the unique id for the source event:
        - WhatsApp inbound: msg.raw["messages"][0]["id"] (the wamid.* string)
        - HTTP/console inbound: a stable hash of (party, text, timestamp) — or None
          if the channel can't produce one (then dedup is a no-op).
        - resolve hook: f"resolve:{task_key}"
        - surface_to_customer: f"surface:{task_key}:{uuid4().hex}"

    `runner` is the drain pipeline for this party. Stash it on the scheduled
    drain task so it always uses the right pipeline.
    """
    if dedup_id is not None:
        if not _redis_queue.set_if_absent(_dedup_key(dedup_id), "1", DEDUP_TTL_SECONDS):
            logger.info("ingest deduped party=%s dedup_id=%s", party, dedup_id)
            return False
    _redis_queue.push(_inbox_key(party), item, ttl_seconds=INBOX_TTL_SECONDS)
    _schedule_drain(party, runner)
    return True


def peek(party: PartyKey) -> list[dict]:
    """Read all queued items without removing them."""
    return [parsed for _, parsed in _redis_queue.peek_with_tokens(_inbox_key(party))]


def _peek_with_tokens(party: PartyKey) -> list[tuple[str, dict]]:
    return _redis_queue.peek_with_tokens(_inbox_key(party))


def _schedule_drain(party: PartyKey, runner: DrainRunner) -> None:
    if party in _SCHEDULED_DRAINS:
        # A drain is already pending; if one is currently running, mark it
        # for redrain so it loops instead of releasing.
        _PENDING_REDRAIN.add(party)
        return
    _SCHEDULED_DRAINS.add(party)
    asyncio.create_task(_drain_after_window(party, runner))


async def _drain_after_window(party: PartyKey, runner: DrainRunner) -> None:
    try:
        await asyncio.sleep(DRAIN_WINDOW_SECONDS)
    finally:
        _SCHEDULED_DRAINS.discard(party)

    owner = uuid4().hex
    if not _redis_queue.acquire_lock(_lock_key(party), owner, ttl_seconds=LOCK_TTL_SECONDS):
        # Another drain is in flight. Mark redrain so it loops on completion.
        _PENDING_REDRAIN.add(party)
        return

    try:
        while True:
            tokens_and_items = _peek_with_tokens(party)
            if not tokens_and_items:
                break
            tokens = [t for t, _ in tokens_and_items]
            items = [i for _, i in tokens_and_items]
            try:
                await runner(party, items)
            except Exception:
                logger.exception("drain runner failed party=%s", party)
                # Leave items queued for the next drain. Do NOT drain on failure.
                return
            _redis_queue.drain_specific(_inbox_key(party), tokens)
            # Did anyone request a redrain while we ran?
            if party not in _PENDING_REDRAIN:
                break
            _PENDING_REDRAIN.discard(party)
    finally:
        _redis_queue.release_lock(_lock_key(party), owner)
        # Trailing safety: if a webhook ingest happened after we cleared
        # SCHEDULED_DRAINS but bailed because the lock was held, ensure
        # those items get a fresh drain.
        if peek(party):
            _schedule_drain(party, runner)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_user_message_item(
    *, text: str, raw: dict | None = None, dedup_id: str | None = None
) -> dict:
    return {
        "type": "user_message",
        "payload": {"text": text, "raw": raw or {}},
        "enqueued_at": now_iso(),
        "dedup_key": dedup_id,
    }


def make_system_event_item(
    *, summary: str, source: str, dedup_id: str | None = None, **extras
) -> dict:
    payload = {"summary": summary, "source": source, **extras}
    return {
        "type": "system_event",
        "payload": payload,
        "enqueued_at": now_iso(),
        "dedup_key": dedup_id,
    }
```

---

## Step 3 — `backend/chatbot/conversations/conversation.py`

The drain pipeline, parameterized by agent + history store + identity resolver + prompt renderer.

```python
"""Conversation — the parameterized drain pipeline.

One Conversation per party (customer or vendor) is what the inbox drain task
calls. It encapsulates: identity resolution → prompt build → agent.run →
send → history append. It does NOT manage the inbox or lock — those are the
inbox module's job.

The two factory functions in `registry.py` build customer and vendor
Conversations with the right parts wired up. Webhook handlers and the
resolve hook obtain a Conversation from the registry, then call
inbox.ingest(party, item, runner=conversation.drain).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from backend.chatbot.channels.base import ChannelIdentity
from backend.chatbot.conversations.inbox import PartyKey

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Conversation:
    party: PartyKey
    agent: Agent
    # Async functions; signatures match the existing chat_storage helpers.
    load_history: Callable[[PartyKey], Awaitable[list]]
    append_history: Callable[[PartyKey, list], Awaitable[None]]
    # Resolver returns the ChannelIdentity to send the reply on, or None when
    # the party has no channel on file (rare for vendor; possible for customer
    # if a webhook never landed).
    resolve_identity: Callable[[PartyKey], Awaitable[ChannelIdentity | None]]
    # Build the system/user prompt from a list of inbox items.
    render_prompt: Callable[[list[dict]], str]
    # Build the agent's deps for this run.
    build_deps: Callable[[PartyKey], Any]
    # Send hook: takes the resolved identity and the agent's text, dispatches
    # via the channel layer. Centralized so customer and vendor variants can
    # add tags / formatting before send.
    send: Callable[[ChannelIdentity, str], Awaitable[None]]
    usage_limits: UsageLimits | None = None

    async def drain(self, party: PartyKey, items: list[dict]) -> None:
        """Run the agent against `items` and send the reply. Raises on transient
        failure so the inbox keeps the items queued for retry."""
        identity = await self.resolve_identity(party)
        if identity is None:
            logger.warning(
                "no identity on file; leaving %d items queued party=%s",
                len(items),
                party,
            )
            # Raise so the inbox treats this as a transient failure and does
            # not drain the items. They'll be picked up next time identity is
            # available.
            raise RuntimeError(f"no_identity_for_{party.kind}")

        prompt = self.render_prompt(items)
        history = await self.load_history(party)
        deps = self.build_deps(party)

        kwargs: dict[str, Any] = {"deps": deps, "message_history": history}
        if self.usage_limits is not None:
            kwargs["usage_limits"] = self.usage_limits

        result = await self.agent.run(prompt, **kwargs)
        await self.send(identity, result.output)
        # Persist only on successful send. If send raised, history stays as-is
        # and the items are NOT drained (we re-raise above).
        await self.append_history(party, result.new_messages())
```

Notes:
- This deliberately does NOT acquire any lock. The inbox module owns the lock.
- `drain` raises on identity-missing or send failure so the inbox keeps items queued. That's the atomicity contract.

---

## Step 4 — `backend/chatbot/conversations/registry.py`

Two factory functions that wire up customer + vendor Conversations.

```python
"""Conversation factories — customer and vendor.

Customer: central_agent + customer history + most-recent channel identity +
inbox-style prompt renderer (mirrors today's orchestrator._build_prompt).

Vendor: outbound_agent + contact history + per-contact identity + plain-join
prompt renderer (mirrors today's outbound.deliver_contact_reply joined input).
"""

from __future__ import annotations

from uuid import UUID

from pydantic_ai.usage import UsageLimits

from backend.chatbot.agents.central import agent as central_agent
from backend.chatbot.agents.deps import AgentDeps
from backend.chatbot.agents.outbound import (
    OutboundDeps,
    _contact_identity,            # existing helper
    _send_to_party,               # existing helper, expects contact_id+text
    outbound_agent,
)
from backend.chatbot.channels import registry as channel_registry
from backend.chatbot.channels.base import ChannelIdentity
from backend.chatbot.conversations.conversation import Conversation
from backend.chatbot.conversations.inbox import PartyKey
from backend.chatbot.messaging import dispatcher as messaging_dispatcher
from backend.db import channel_identities, chat_storage, contacts, outbound_ledger

_CENTRAL_USAGE_LIMITS = UsageLimits(request_limit=10)


# --- Customer side -----------------------------------------------------------

async def _load_customer_history(party: PartyKey):
    return await chat_storage.load_history(party.business_id, party.party_id)


async def _append_customer_history(party: PartyKey, messages: list) -> None:
    await chat_storage.append_history(party.business_id, party.party_id, messages)


async def _resolve_customer_identity(party: PartyKey) -> ChannelIdentity | None:
    return await channel_identities.get_most_recent_identity(
        UUID(party.business_id), UUID(party.party_id)
    )


def _render_customer_prompt(items: list[dict]) -> str:
    parts: list[str] = ["Customer messages this turn:"]
    for it in items:
        if it.get("type") == "user_message":
            text = it.get("payload", {}).get("text") or ""
            parts.append(f"- {text}")
        elif it.get("type") == "system_event":
            summary = it.get("payload", {}).get("summary") or ""
            parts.append(f"- (system) {summary}")
    return "\n".join(parts)


def _build_customer_deps(party: PartyKey) -> AgentDeps:
    return AgentDeps(
        customer_id=UUID(party.party_id),
        business_id=UUID(party.business_id),
        state={},
        outbound=[],
    )


async def _send_customer(identity: ChannelIdentity, text: str) -> None:
    channel = channel_registry.get(identity.channel)
    await messaging_dispatcher.dispatch_to_customer(channel, identity, text)


def customer_conversation(business_id: str, customer_id: str) -> Conversation:
    return Conversation(
        party=PartyKey.customer(business_id, customer_id),
        agent=central_agent,
        load_history=_load_customer_history,
        append_history=_append_customer_history,
        resolve_identity=_resolve_customer_identity,
        render_prompt=_render_customer_prompt,
        build_deps=_build_customer_deps,
        send=_send_customer,
        usage_limits=_CENTRAL_USAGE_LIMITS,
    )


# --- Vendor side -------------------------------------------------------------

async def _load_vendor_history(party: PartyKey):
    return await chat_storage.load_contact_history(
        UUID(party.business_id), UUID(party.party_id)
    )


async def _append_vendor_history(party: PartyKey, messages: list) -> None:
    await chat_storage.append_contact_history(
        UUID(party.business_id), UUID(party.party_id), messages
    )


async def _resolve_vendor_identity(party: PartyKey) -> ChannelIdentity | None:
    return await _contact_identity(UUID(party.party_id))


def _render_vendor_prompt(items: list[dict]) -> str:
    # Vendor inbox holds only user_message items today (vendor doesn't receive
    # system_events). Join texts in order, mirroring the old behavior.
    texts = [
        it.get("payload", {}).get("text", "").strip()
        for it in items
        if it.get("type") == "user_message"
    ]
    return "\n".join(t for t in texts if t)


async def _build_vendor_deps(party: PartyKey) -> OutboundDeps:
    biz = UUID(party.business_id)
    cid = UUID(party.party_id)
    contact = await contacts.get_by_id(cid)
    if contact is None:
        raise ValueError(f"contact {cid} missing")
    open_tasks = await outbound_ledger.list_open_tasks_by_contact(biz, cid)
    return OutboundDeps(
        business_id=biz,
        contact_id=cid,
        contact_name=contact.name,
        contact_role=contact.role,
        open_tasks=open_tasks,
    )


# build_deps is sync in Conversation, so we wrap _build_vendor_deps in a thunk.
# Conversation.drain awaits build_deps's return value if it's a coroutine — to
# keep things simple, change Conversation.build_deps to allow Awaitable[Any]
# return; or implement build_deps as a sync function that returns a coroutine.
# Cleaner: make build_deps Callable[[PartyKey], Awaitable[Any]] uniformly, and
# update _build_customer_deps to be `async def`.

# IMPORTANT for implementer: pick one — either both build_deps are async (and
# Conversation.drain awaits), or both are sync. Recommend: make both async for
# flexibility. Update Conversation accordingly.


async def _send_vendor(identity: ChannelIdentity, text: str) -> None:
    # Outbound's existing _send_to_party handles channel registry + dispatch.
    # We bypass it and use the channel directly because we already have the
    # resolved identity in hand.
    channel = channel_registry.get(identity.channel)
    await channel.send(identity, text)


def vendor_conversation(business_id: str, contact_id: str) -> Conversation:
    return Conversation(
        party=PartyKey.vendor(business_id, contact_id),
        agent=outbound_agent,
        load_history=_load_vendor_history,
        append_history=_append_vendor_history,
        resolve_identity=_resolve_vendor_identity,
        render_prompt=_render_vendor_prompt,
        build_deps=_build_vendor_deps,
        send=_send_vendor,
        usage_limits=None,
    )
```

**IMPORTANT note for the implementer of Step 2/3**: `build_deps` should be `async def` for both customer and vendor (vendor needs DB lookups). Update `Conversation.build_deps` type to `Callable[[PartyKey], Awaitable[Any]]`, and make `_build_customer_deps` an `async def`. Drain becomes `deps = await self.build_deps(party)`.

---

## Step 5 — Webhook + CLI rewiring

### `backend/api/routers/webhooks/whatsapp.py`

Replace the existing `match sender.kind` block:

```python
case "contact":
    text = msg.text or ""
    if not text:
        # ... (unchanged guard)
        return {"ok": True, "ignored": "contact_no_text"}
    biz = str(sender.business_id)
    cid = str(sender.contact_id)
    party = PartyKey.vendor(biz, cid)
    convo = vendor_conversation(biz, cid)
    inbox.ingest(
        party,
        inbox.make_user_message_item(text=text, raw=msg.raw, dedup_id=_wamid(msg)),
        dedup_id=_wamid(msg),
        runner=convo.drain,
    )
    return {"ok": True}
case "customer":
    customer_uuid = await resolve_or_create_customer_by_phone(wa_id)
    biz = str(sender.business_id)
    cust = str(customer_uuid)
    # Persist identity here (used to live in orchestrator.handle_inbound).
    resolved_identity = ChannelIdentity(
        business_id=biz,
        customer_id=cust,
        channel="whatsapp",
        channel_user_id=wa_id,
        channel_business_id=phone_number_id,
        last_inbound_at=msg.identity.last_inbound_at,
    )
    await channel_identities.upsert_identity(resolved_identity.model_copy(
        update={"last_inbound_at": datetime.now(timezone.utc)}
    ))
    party = PartyKey.customer(biz, cust)
    convo = customer_conversation(biz, cust)
    inbox.ingest(
        party,
        inbox.make_user_message_item(text=msg.text or "", raw=msg.raw, dedup_id=_wamid(msg)),
        dedup_id=_wamid(msg),
        runner=convo.drain,
    )
    return {"ok": True}
```

Helper to extract the wamid:

```python
def _wamid(msg) -> str | None:
    """Extract Meta's per-message id from the parsed inbound. None if missing."""
    try:
        return msg.raw.get("messages", [{}])[0].get("id")
    except (AttributeError, IndexError):
        return None
```

### `backend/api/routers/webhooks/http.py`

```python
@router.post("/http")
async def http_inbound(request: Request) -> dict:
    payload = await request.json()
    channel = registry.get("http")
    msg = channel.parse_inbound(payload)
    biz = msg.identity.business_id
    cust = msg.identity.customer_id
    convo = customer_conversation(biz, cust)
    inbox.ingest(
        PartyKey.customer(biz, cust),
        inbox.make_user_message_item(text=msg.text or "", raw=msg.raw),
        dedup_id=None,  # http channel has no native dedup id; tests can pass one
        runner=convo.drain,
    )
    return {"ok": True}
```

### CLI / smoke script

Search for any other callers of `orchestrator.handle_inbound`, `inbox.enqueue`, `contact_inbox.enqueue`, `wake_central`, `deliver_system_event`. Rewrite each to use `inbox.ingest` with the right Conversation.

Likely callers: `cli/`, `tests/`, `app/main.py`, `test_*.py`.

---

## Step 6 — Coordinator merge + simplified hook

### `backend/chatbot/agents/outbound.py` modifications

1. **Add coordinator tools** to `outbound_agent` directly. Pull from `coordinator.py`:
   - `update_inventory(sku, delta)`
   - `update_price(sku, new_price)`
   - `update_vendor_contact(vendor_id, fields)`
   - `record_note(subject, content)`
   - `coord_list_contacts(role=None)` — rename if it conflicts; or add to outbound's tool surface as a fresh tool. Outbound currently has no list_contacts tool, so use `list_contacts` directly.
   - `dispatch_outbound(contact_id, prompt, summary=None, timeout_seconds=3600)` — opens a new outbound thread (the coordinator's existing tool, just merged in)
   - `escalate_to_operator(reason, options=None)` — log only (TODO marker)
   - `surface_to_customer(summary)` — see below

   These become `@outbound_agent.tool` and accept `RunContext[OutboundDeps]`. Replace `ctx.deps.business_id` (UUID), `ctx.deps.customer_id` (UUID — note: outbound currently has only `business_id` + `contact_id` on its deps; you need to add `customer_id` to OutboundDeps if a tool needs it). Inspect each tool: `update_inventory`/`update_price`/`update_vendor_contact`/`record_note`/`list_contacts`/`escalate_to_operator` only need `business_id`. `dispatch_outbound` and `surface_to_customer` need `customer_id`.

   **Resolution**: Add `customer_id: UUID | None` to `OutboundDeps`. Set it from `outbound_ledger` lookup at deps build time (vendor inbound's ledger row has the `customer_id`). For dispatch (opening), it's already known by the caller. The vendor conversation factory's `_build_vendor_deps` should include the `customer_id` from the most-recent open task or any task on this contact:

   ```python
   open_tasks = await outbound_ledger.list_open_tasks_by_contact(biz, cid)
   customer_id_for_deps = open_tasks[0].customer_id if open_tasks else None
   ```

   Tools that need a `customer_id` and find it None should return `{"ok": False, "reason": "no_customer_context"}` and let the agent decide what to do.

2. **Rewrite `_on_resolve_tasks` hook** to ingest directly into the customer inbox and drop `outbound_resolution.route`:

   ```python
   from backend.chatbot.conversations import inbox as conv_inbox
   from backend.chatbot.conversations.inbox import PartyKey
   from backend.chatbot.conversations.registry import customer_conversation

   @_hooks.on.after_tool_execute(tools=["resolve_tasks"])
   async def _on_resolve_tasks(ctx, /, *, call, tool_def, args, result):
       acknowledged = result.get("acknowledged", []) if isinstance(result, dict) else []
       if not acknowledged:
           return result
       for task_key in acknowledged:
           task = await outbound_ledger.get_by_key(task_key)
           if task is None or not task.customer_context:
               continue
           biz = str(task.business_id)
           cust = str(task.customer_id)
           convo = customer_conversation(biz, cust)
           conv_inbox.ingest(
               PartyKey.customer(biz, cust),
               conv_inbox.make_system_event_item(
                   summary=task.customer_context,
                   source="outbound_reply",
                   contact_name=task.contact_name,
                   contact_role=task.contact_role,
                   task_key=task.task_key,
                   dedup_id=f"resolve:{task_key}",
               ),
               dedup_id=f"resolve:{task_key}",
               runner=convo.drain,
           )
       return result
   ```

3. **`surface_to_customer` becomes**:

   ```python
   @outbound_agent.tool
   async def surface_to_customer(ctx: RunContext[OutboundDeps], summary: str) -> dict:
       if ctx.deps.customer_id is None:
           return {"ok": False, "reason": "no_customer_context"}
       biz = str(ctx.deps.business_id)
       cust = str(ctx.deps.customer_id)
       convo = customer_conversation(biz, cust)
       conv_inbox.ingest(
           PartyKey.customer(biz, cust),
           conv_inbox.make_system_event_item(
               summary=summary,
               source="outbound_surface",
               dedup_id=f"surface:{uuid4().hex}",
           ),
           dedup_id=f"surface:{uuid4().hex}",
           runner=convo.drain,
       )
       return {"ok": True}
   ```

4. **Update `OutboundDeps`**: add `customer_id: UUID | None = None`. The vendor conversation builder populates it from the latest open task.

5. **Update `outbound_agent.instructions`** — fold the coordinator instructions in. The outbound agent now plays both roles: vendor conversation manager AND back-office bookkeeper after a resolution. Adjust `_INSTRUCTIONS` to mention the new tools (inventory, prices, contacts, surface_to_customer) and when to use them. Keep the customer/vendor voice rules intact.

### Files to delete in this step

- `backend/chatbot/agents/coordinator.py`
- `backend/chatbot/routers/outbound_resolution.py`
- `backend/chatbot/routers/__init__.py` if it becomes empty (check first)

---

## Step 7 — Final cleanup

After Steps 1-6 land:

1. Verify no remaining imports of:
   - `backend.chatbot.orchestrator`
   - `backend.chatbot.inbox`
   - `backend.chatbot.contact_inbox`
   - `backend.chatbot.routers.outbound_resolution`
   - `backend.chatbot.agents.coordinator`

   Use `grep -rn 'from backend.chatbot.orchestrator' app/` etc. Fix every hit.

2. Delete the four old modules (`orchestrator.py`, `inbox.py`, `contact_inbox.py`, `routers/outbound_resolution.py`).

3. Search for stale references in CLI, tests, scripts, smoke utilities. Common pattern: `from backend.chatbot import inbox` — replace with `from backend.chatbot.conversations import inbox`.

4. Search for `wake_central` and `deliver_system_event` callers. Both should be replaced with direct `inbox.ingest(...)` calls.

---

## Step 8 — Tests

1. Run existing pytest suite. Fix any breakage.
2. Add a unit test for `inbox.ingest` dedup: ingesting the same `dedup_id` twice should enqueue once.
3. Add a unit test for `drain_specific`: an item pushed during a fake "agent run" survives the drain.
4. Verify customer-inbound smoke flow (HTTP webhook): message → agent → reply.
5. Verify the new vendor-resolution path: simulate an outbound `resolve_tasks` with `customer_context` set; assert the customer inbox sees a `system_event` and the central agent runs after the debounce.

---

## Conventions all agents must follow

- **Branch**: stay on `march-refactor`. Do not create new branches.
- **Commits**: leave commits to the human; do not run `git commit` or `git push`.
- **Imports**: project root is `app/backend`. Imports start `backend.…` (see `outbound.py:44`).
- **No new test files** unless Step 8 specifies them. Modify existing tests to match new structure.
- **Docstrings**: short, focused, only when WHY isn't obvious. No multi-paragraph blocks. Mirror the existing house style (see `_redis_queue.py`, `inbox.py`).
- **No emojis**, no ceremony, no defensive try/except around things that "shouldn't fail" — only catch where the design here explicitly says to.
- **Logging**: use module-level `logger = logging.getLogger(__name__)`. Match phrasing of existing logs (lowercase, `key=val` shape).
- **Type hints**: Python 3.11+ syntax. `list[dict]`, `str | None`, etc.
- **Dataclasses**: `@dataclass(frozen=True)` for value types (PartyKey, Conversation).
- **Don't introduce new abstractions** beyond what's specified here.
