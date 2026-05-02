# Ottobiz Architecture Brief

A short, citation-heavy map of how messages flow in/out of the system, focused on the three live bugs:

1. Vendor inbound being treated as a customer
2. Vendor resolutions never reaching the customer
3. The `after_tool_execute` hook on `resolve_tasks`

---

## 1. Top-level flow

```
                            ┌───────────────────────────────────────┐
                            │  POST /webhooks/whatsapp              │
                            │  app/backend/api/routers/webhooks/    │
                            │      whatsapp.py:67                   │
                            └────────────────┬──────────────────────┘
                                             │
                       resolve_inbound_sender(phone_number_id, wa_id)
                       app/backend/chatbot/channels/whatsapp_resolver.py:31
                                             │
                ┌────────────────┬───────────┼──────────────────────┐
                │                │           │                      │
        unknown_tenant         owner       contact                customer
        (drop, 200)            (drop)        │                      │
                                             │                      │
                                             ▼                      ▼
                          contact_inbox.enqueue          orchestrator.handle_inbound
                          (20s debounce window)          (per-customer Redis lock)
                          contact_inbox.py:40,104        orchestrator.py
                                             │                      │
                                             ▼                      ▼
                            outbound.deliver_contact_reply   _drain_and_reply
                            outbound.py:474                  orchestrator.py:168
                                             │                      │
                                             ▼                      ▼
                              outbound_agent.run()           central_agent.run()
                              (vendor-side conversation)     (customer-side reply)
                                             │                      │
                          (model calls resolve_tasks)                │
                                             │                      │
                          @after_tool_execute hook                   │
                          outbound.py:191                            │
                                             │                      │
                              outbound_resolution.route(task_key)    │
                              routers/outbound_resolution.py:30      │
                                             │                      │
                              ┌──────────────┼─────────────┐         │
                              ▼              ▼             ▼         │
                       coordinator    inbox.enqueue   wake_central ──┘
                       (system_ctx)   (customer_ctx)  (system-initiated run)
```

Two parallel inbound queues, two locks, three agents. The whole thing is held together by **`channel_identities`** for outbound sends and the **`outbound_tasks`** ledger for cross-thread state.

---

## 2. Identity resolution — where customer vs vendor is decided

Single SQL query, `whatsapp_resolver.py:31-74`:

```sql
SELECT b.id AS biz, c.id AS contact_id, c.role
FROM businesses b
LEFT JOIN contacts c
  ON c.business_id = b.id
 AND c.channel = 'whatsapp'
 AND c.channel_user_id = $2
WHERE b.whatsapp_phone_number_id = $1
```

Decision tree (`whatsapp_resolver.py:64-74`):
- `contact_id IS NOT NULL` → **kind="contact"** (vendor/logistics)
- `wa_id == business.owner_phone_number` → **kind="owner"** (drop)
- otherwise → **kind="customer"** (auto-create user)

That LEFT JOIN is the **only** thing separating a vendor from a customer. If the row isn't in `contacts`, the sender is treated as a customer — there's no second guard.

---

## 3. Agents

| Agent | File | Role | Talks to | Triggered by |
|---|---|---|---|---|
| **central** | `agents/central.py` | Sole customer voice | Customer (WhatsApp) | `_drain_and_reply` from customer inbox |
| **outbound** | `agents/outbound.py` | Vendor-side conversation | Vendor (WhatsApp) | `deliver_contact_reply` after debounce; `dispatch` for new threads |
| **coordinator** | `agents/coordinator.py` | Back-office bookkeeping (inventory, contacts, surface-to-customer) | Nobody directly | `outbound_resolution.route` when `system_context` is set |

Subagent tools (`product`, `payment`, `logistics`, `customer_relation`, `media`) are reachable from `central` via a `query_subagent` dispatch tool. `outbound` is **not** invoked by the customer-side agent at message time — it runs only on the contact-inbox path.

---

## 4. The `after_tool_execute` hook on `resolve_tasks`

Defined at `agents/outbound.py:191-217`:

```python
@_hooks.on.after_tool_execute(tools=["resolve_tasks"])
async def _on_resolve_tasks(ctx, /, *, call, tool_def, args, result):
    acknowledged = result.get("acknowledged", []) if isinstance(result, dict) else []
    if not acknowledged:
        return result
    await asyncio.gather(
        *(route(task_key) for task_key in acknowledged),
        return_exceptions=True,
    )
    return result
```

- **Fires after** `resolve_tasks` returns to the model — pydantic-ai hook contract
- **Inputs**: only the tool's return value (`{"acknowledged": [...], "skipped": [...]}`); does **not** re-read the ledger
- **Effect**: fan-out `route(task_key)` per acknowledged task in parallel, isolated with `return_exceptions=True`
- **Registration**: requires `capabilities=[_hooks]` on the `Agent(...)` constructor (`outbound.py:220-225`) — without that, the hook silently no-ops
- **Failure modes**:
  - `result` not a dict → hook returns early, no route
  - `acknowledged == []` → no route (vendor reply did not close anything)
  - Agent never calls `resolve_tasks` → hook never fires (silent)

`route()` is the thing that actually puts work on the customer inbox. The hook's only job is to invoke it.

---

## 5. `outbound_resolution.route(task_key)` — the bridge back to the customer

`routers/outbound_resolution.py:30-94`. Three independent steps, each in its own `try/except` (post-26fb128):

1. **Coordinator pass** (`system_context` set) — runs coordinator agent under per-customer lock. Errors logged, **does not abort** (fix from `9da898d`).
2. **Customer enqueue** (`customer_context` set) — `inbox.enqueue(biz, cust, _outbound_reply_item(task))`. The item is a `system_event` containing `summary = task.customer_context`. On exception, it returns early — `wake_central` is **not** attempted.
3. **Wake central** — `await orchestrator.wake_central(biz, cust)`. Acquires the per-customer lock, peeks the inbox, runs central once, sends, drains. On exception, items remain queued for the next inbound.

Two preconditions for the customer to see anything:
- `task.customer_context` must be non-empty (set by `resolve_tasks` → `mark_completed` at `outbound_ledger.py:259-266`)
- `wake_central` must succeed end-to-end, including the WhatsApp send, which needs `channel_business_id` on the saved identity (`147d901`).

---

## 6. State

- **Customer inbox** — Redis `inbox:{biz}:{cust}` (`inbox.py:20`). Items: `user_message` or `system_event`.
- **Contact inbox** — Redis `contact_inbox:{biz}:{contact}` (`contact_inbox.py:45`). Raw debounced text only.
- **Customer lock** — `lock:inbox:{biz}:{cust}` (60s TTL). Held by `handle_inbound`, `wake_central`, `_run_coordinator`.
- **Contact lock** — `lock:contact_inbox:{biz}:{contact}`. Held by debounce drain and outbound dispatch.
- **Ledger** — Postgres `outbound_tasks` (`db/outbound_ledger.py`). Tracks state machine, customer_context, system_context, contact_id, timeouts.
- **Channel identities** — Postgres `channel_identities`, now carries `channel_business_id` (`147d901`) so system-initiated sends know the WhatsApp `phone_number_id`.
- **Chat history** — separate stores for customer (`chat_storage.load_history`) and contact (`load_contact_history`).

---

## 7. Findings on the live bugs

### Bug 1 — vendor inbound treated as customer

The split happens entirely at `whatsapp_resolver.py:64`. There's no fallback heuristic — if the vendor's `wa_id` is missing from `contacts` (or stored under a different `business_id` / format / channel), the resolver returns `kind="customer"` and `whatsapp.py:126-138` ships the message to `orchestrator.handle_inbound`, which runs `central_agent`. From central's point of view it is a customer, so it tries to "help" them.

Likely causes (in order of probability):
1. **Contact row missing** for that vendor wa_id under that business. Verify with:
   ```sql
   SELECT id, role, channel_user_id
   FROM contacts
   WHERE business_id = '<biz>' AND channel = 'whatsapp' AND channel_user_id = '<wa_id>';
   ```
2. **wa_id format mismatch** — Meta's `wa_id` vs what was stored when the contact was created (e.g. leading `+`, country code stripped). The JOIN is exact-match.
3. **Wrong tenant** — webhook hit a `phone_number_id` that doesn't match `businesses.whatsapp_phone_number_id`, returning `kind="unknown_tenant"`. (This drops, doesn't reach central — so it's unlikely to be your symptom but worth ruling out.)

There is **no defense in depth** here. The resolver is the single point of decision; a missing/wrong contacts row → vendor becomes a customer. Worth considering a check on outbound-pending state too: if there's a live `outbound_tasks` row for this `(business, channel_user_id)`, treat as contact even when no contacts row exists.

### Bug 2 — vendor reply never reaches the customer

Pre-conditions for the customer to be woken:
- Vendor message reaches `outbound_agent` (i.e., bug 1 doesn't intervene)
- Agent calls `resolve_tasks` with at least one item that the tool actually marks acknowledged
- Hook is registered (`capabilities=[_hooks]`) and fires
- `route()` succeeds at `inbox.enqueue` and `wake_central`
- `wake_central` finds the system_event, runs central, central sends a WhatsApp message — which requires `channel_business_id` to be present on the identity

Each of these has been broken at some point in the last day:

| Commit | Fixed |
|---|---|
| `0adefe6` | Inlined `route()` into tool body — was a workaround for an apparent hook no-op |
| `9da898d` | Wrapped `_run_coordinator` in try/except so a coordinator crash no longer aborts customer wake |
| `26fb128` | Split route into three isolated steps, each with logfire spans (was previously invisible) |
| `26fcf0b` | Moved `route()` back into the `after_tool_execute` hook now that it's confirmed firing |
| `147d901` | Persisted `channel_business_id` on `channel_identities` so system-initiated sends have a valid `phone_number_id` |

The most likely remaining failure modes:
- **Agent never calls `resolve_tasks`.** The vendor's text closed the task in their mind, but the LLM produced a plain text reply. Hook can't fire on a tool that wasn't called. Check the logfire span tree for the `outbound_agent.run()` — is there a `tool: resolve_tasks` child? If not, this is the bug.
- **`customer_context` is empty.** `_outbound_reply_item` builds `summary = task.customer_context or ""`. Central will see a system_event with empty content and may produce nothing. Check the ledger row's `customer_context` column after a vendor reply.
- **`wake_central` succeeds but central produces no output / fails to send.** Check the central run span for tool errors or missing identity.

### Bug 3 — does the hook actually post the customer context to central's inbox?

Yes, indirectly. The hook calls `route()`; `route()` calls `inbox.enqueue()` with a `system_event` whose payload is:

```python
{
  "type": "system_event",
  "payload": {
    "summary": task.customer_context or "",
    "source": "outbound_reply",
    "contact_name": task.contact_name,
    "contact_role": task.contact_role,
    "task_key": task.task_key,
  },
  "enqueued_at": <iso>,
}
```

(`outbound_resolution.py:97-108`). Then `wake_central` is called. Central reads the inbox in `_drain_and_reply`, sees the `system_event`, and is expected to phrase it for the customer.

Things to verify:
- The system_event is actually rendered into central's prompt (vs. being silently dropped during `_drain_and_reply`'s prompt build) — check `orchestrator.py:168` and surrounding rendering.
- `task.customer_context` is non-empty when `mark_completed` runs (`outbound_ledger.py:259-266`); the agent must pass a real `customer_context` field to `resolve_tasks`, not omit it.
- Identity loaded for the send carries `channel_business_id` (post-`147d901`).

---

## 8. What to instrument next

A single end-to-end logfire trace covering one vendor reply: webhook → contact_inbox → debounce → outbound_agent.run → resolve_tasks tool → after_tool_execute hook → route() → inbox.enqueue → wake_central → central.run → WhatsApp send. With `26fb128` you should already have spans for the `route()` half; the missing piece is whether `resolve_tasks` is called at all and whether `customer_context` is populated. If both are true and the customer still doesn't see anything, the failure is downstream in `wake_central` / central's prompt rendering / WhatsApp send (likely identity-related).
