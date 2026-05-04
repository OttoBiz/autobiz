# Customer journey: risks, failure modes, and hardening

This document expands on operational and architectural risks for the path **product enquiry → purchase → delivery** in this backend. It assumes the high-level flow in `architectural_workflow.md`: customer chat uses an orchestrator and specialists; **Redis** holds `user_state` (including `processes` and `chat_history`); the **central agent** coordinates vendor/logistics; **PostgreSQL** holds orders and business data.

The goal is not to list every bug, but to explain **what can go wrong**, **why it happens**, and **what hardening usually looks like**—so you can prioritize work deliberately.

---

## 1. How the journey is wired (mental model)

1. **Customer** talks to the **conversational agent**, which may hand off to **specialists** (product, payment, logistics, etc.).
2. Each meaningful “thread” is often tracked as a **`process`** in `user_state["processes"]` (keyed by `process_id`), with fields like `product_name`, `order_id`, `task_type`, and sometimes `completed`.
3. **Central agent** runs when sub-agents or flows need to notify **vendor** or **logistics**, or to drive multi-party logic; it reads/writes the same Redis state and may create or update **orders** in the DB.
4. **Paystack** (and similar) may confirm payment via **webhooks** or in-chat verification; **orders** are created when business rules say payment is confirmed.

If any layer **disagrees** (Redis vs DB, chat vs webhook, two processes for one purchase), the user can see a **coherent message** while the **system of record** is wrong—that is often worse than a hard error.

---

## 2. State and process lifecycle

### 2.1 Redis as source of truth

**What it means:** Session state (chat history, product caches, `processes`) lives primarily under keys such as `{user_id}:{vendor_id}` (and party keys for vendor/logistics chat).

**What can go wrong:**

- **Lost keys:** Redis flush, mis-keyed deletes, or operational mistakes can wipe in-flight processes. The customer may still have a browser session, but the backend has no memory of `process_id` or order linkage.
- **TTL (time-to-live):** If you later add automatic expiry on keys, long conversations could **lose state mid-journey** unless you persist critical facts to Postgres or refresh TTL on activity.
- **Concurrent writes:** Two requests updating the same `user_state` without read-modify-write discipline can **overwrite** each other’s `processes` updates, leaving partial or inconsistent dicts.

**Where that pattern exists in code (same Redis key `{user_id}:{vendor_id}`):** `chatbot/interface/user_chat_interface._chat_inner` (per-turn save after the orchestrator), `api/routers/payments.paystack_webhook` (merges `paystack_webhook_confirmed`), `db/cache_utils.append_inbox_turn_to_customer_pair`, `central_agent` tools that load/save state (`create_order`, `update_order_status`, `mark_task_finished`, `mark_process_completed`), and `polish_central_message_for_customer` if it overlaps another request for the same pair. Party keys `{vendor_id}` / `{logistic_id}` have the same class of risk via `modify_party_state`. Nothing here uses Redis transactions; overlapping requests are last-write-wins.

**Hardening direction:** Treat Redis as **fast session cache**; persist **order IDs**, **payment references**, and **process completion** in Postgres when they become business-critical. Implemented: `paystack_webhook_events` (idempotent by reference), `order_process_links` (order ↔ `process_id`), capped Redis `paystack_webhook_confirmed`, inbox push retries + correlated logs, and `scripts/reconcile_paystack_orders.py` for heuristic gaps.

### 2.2 `completed` and pruning

**What it means:** Processes can be marked `completed` (e.g. after delivery is done). Completed entries may be **removed** from `processes` so the UI and instructions focus on **open** work.

**What can go wrong:**

- **Too early completion:** If `mark_process_completed` (or equivalent) runs before the customer is truly done (e.g. payment pending, return in progress), the UI may **hide** the active flow; the model may lose **context** for the next turn.
- **Never completed:** Old processes accumulate; routing by product name alone can attach new messages to the **wrong** process, or instructions become noisy.

**Hardening direction:** Define **clear completion criteria** per `task_type`; optionally keep a **short summary** in Postgres when pruning Redis.

### 2.3 Multiple open processes for the same product or order

**What it means:** A customer might start several enquiries or have retries, producing multiple `process_id` values.

**What can go wrong:**

- Handoffs without an explicit **`process_id`** may let the specialist or central agent pick the **wrong** process (e.g. older enquiry vs current purchase).
- **Central** may append to **communication_history** on one process while the customer believes they are discussing another.

**Hardening direction:** Pass **`process_id`** on handoffs when known; prefer **explicit** process selection in tools over fuzzy name matching alone.

---

## 3. Product enquiry → purchase

### 3.1 Catalog vs session cache

**What it means:** The orchestrator may cache browse/search results under `user_state["products"]` with TTL; the product specialist may **refetch** from the DB on each run.

**What can go wrong:**

- **Stale cache:** Prices, stock, or availability shown in an earlier turn may **differ** from what the specialist fetches later—confusing if not acknowledged in copy.
- **Two sources of truth:** The customer believes “what the bot said last time” is still true.

**Hardening direction:** Short TTLs, refetch before purchase, or a single “quote valid at time X” mindset in prompts.

### 3.2 Paystack / bank transfer vs order creation

**What it means:** Payment can succeed in **Paystack** or informally via **bank transfer** while the **order row** is created only when your pipeline (central agent, `create_order`, vendor confirmation) runs successfully.

**What can go wrong:**

- **Money without order:** Webhook or verification succeeds, but **order creation fails** (DB error, bug, timeout). The customer paid; the system has no order—or a half-updated state.
- **Order without payment:** Rarer if you gate on verification, but possible if manual overrides or race conditions exist.

**Hardening direction:** **Idempotent** handling of payment events (same Paystack reference processed once); **reconciliation** job to find payments without orders; **retry** or **alert** on failed `create_order` after verified payment.

### 3.3 Webhook → user resolution and `paystack_webhook_confirmed`

**What it means:** Webhooks often include a **transaction reference**; your app must map that to **`user_id`** and **`business_id`** to update the correct Redis key.

**What can go wrong:**

- If resolution fails (missing mapping, expired Redis key for `paystack_ref:...`), the webhook updates **nothing** or the wrong user; in-chat verification and webhook state **diverge**.
- The list **`paystack_webhook_confirmed`** can grow unbounded per user if never pruned—mostly a **memory/Redis size** issue, not wrong behavior, unless duplicates are mishandled.

**Hardening direction:** Reliable **reference → (user_id, business_id)** storage (Postgres); idempotent append; optional cap or archival.

---

## 4. Purchase → delivery

### 4.1 Logistics party and `partner_logistic_id`

**What it means:** Delivery may involve a **vendor** and a **logistics** business; routing tools need the correct **logistics party id** (e.g. linked on the business or order).

**What can go wrong:**

- **Missing link:** Fallback logic may pick a random logistics company or vendor-only delivery when that is not what the business intended.
- **Wrong link:** Messages or tasks go to the **wrong** logistics inbox.

**Hardening direction:** Explicit business configuration; validate linkage at order creation; surface misconfiguration to admins.

### 4.2 `order_id` vs `process_id` and orders outside chat

**What it means:** `process_id` is a **session** construct; `order_id` is a **database** row. You’ve added resolution paths so logistics/payment can derive `order_id` from `process_id` when needed.

**What can go wrong:**

- Orders created **outside** this chat (admin panel, another integration) never appear under `user_state["processes"]` unless something **syncs** them.
- Manual DB edits can desynchronize **tracking/status** from what Redis still says.

**Hardening direction:** When an order is created or updated, **update** the matching process (or a Postgres link table `process_id ↔ order_id`) so chat and DB stay aligned.

---

## 5. Central agent and vendor path

### 5.1 Single hub failure

**What it means:** `run_central_agent` is the main choke point for **routing** and **vendor/logistics** delivery of structured messages.

**What can go wrong:**

- **Exception:** Customer-facing agent may still return a reply while **central never persisted** or never delivered to the vendor.
- **Inbox delivery failure:** Vendor UI never shows the escalation; customer thinks the store was notified.

**Hardening direction:** Try/except with **logging**; **retry queue** for outbound vendor messages; **correlation ids** (`process_id`, `order_id`) in logs.

### 5.2 `communication_history` summarization

**What it means:** Long per-process threads may be **summarized** to save tokens.

**What can go wrong:**

- Summaries that drop **amounts**, **addresses**, or **deadlines** cause the model to **mis-route** or **promise** incorrectly.

**Hardening direction:** Summarization prompts that **preserve structured facts**; keep the last N raw turns; store critical fields in Postgres, not only in summary text.

---

## 6. Cross-cutting concerns

### 6.1 Idempotency (payments and order creation)

**Definition:** Processing the **same logical event twice** (e.g. duplicate webhook) should not create **two orders** or **double-apply** side effects.

**Why it matters:** HTTP clients and payment providers **retry**; without idempotency you get duplicate rows and angry customers.

**Typical pattern:** Unique key per payment reference (`reference`); store “already processed” in DB; second delivery returns success without re-running side effects.

### 6.2 Auth and tenancy (`business_id` / `user_id`)

**What can go wrong:** Wrong `vendor_id` or `business_id` on the Redis key loads **another store’s** state—catastrophic for privacy and behavior.

**Hardening direction:** Validate **session ↔ business** on every API boundary; never trust client-supplied IDs without auth.

### 6.3 Observability

**What can go wrong:** Without **structured logs** tying `process_id`, `order_id`, `user_id`, `business_id`, and **caller** (`product_agent`, `payment_webhook`, …), production incidents are **hard to replay**.

**Hardening direction:** Correlation IDs; metrics for webhook failures, central failures, and order creation failures.

---

## 7. What “malfunction” looks like in practice

Failures are often **silent** or **partial**:

| Symptom | Possible cause |
|--------|----------------|
| Payment verified but no order | Order creation failed after verification; no reconciliation |
| Wrong tracking / wrong order | Multiple processes; ambiguous routing without `process_id` |
| Specialist has no product context | Missing `process_id` or empty process |
| Customer sees success, DB pending | UI/agent copy ahead of DB commit; no error surfaced |
| Vendor never notified | Central or inbox delivery failed after customer reply |
| Stale prices or stock | Cache TTL vs live DB |

---

## 8. Suggested hardening order (highest leverage first)

1. **Idempotent payment → order pipeline** (webhooks + in-chat verification paths), with **reconciliation** for payments without orders.
2. **Sync DB order ↔ process** when orders are created or updated (including outside chat).
3. **Alerts / metrics** on central failures, webhook resolution failures, and `create_order` failures.
4. **Explicit `process_id`** on handoffs and critical tools where ambiguity exists.
5. **Safer comm summarization** (facts preserved or stored outside the summary).

---

## Related docs

- `architectural_workflow.md` — memory, Redis fields, and workflow overview  
- `paystack_flow.md` — Paystack-specific notes (if present)
