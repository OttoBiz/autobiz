# Architectural Workflow

A concise overview of the Autobiz backend from the first customer message through multi-party coordination and delivery.

**Related:** For operational risks (Redis vs DB, payments, processes, central agent), see [`journey_risks_and_hardening.md`](./journey_risks_and_hardening.md).

---

## 1. System Overview

The backend is a multi-agent chatbot system that automates operations across **customers**, **vendors (businesses)**, and **logistics**.

**State in Redis**

- **Customer–vendor thread:** key `{user_id}:{vendor_id}` — full customer session (chat, products cache, processes, uploaded files, etc.).
- **Vendor or logistics UI thread:** key **`{vendor_id}`** or **`{logistic_id}`** alone — business/logistics chat history and inbox-driven replies.
- **Inbox queue:** key `inbox:{recipient_id}` — pending messages for a party.

**Core components**

- **User Chat Interface** — Customer entry; one orchestrator + persistence on the pair key.
- **Conversational Agent** — Primary store associate for the customer channel; delegates to specialists via **tools** (product, payment, logistics, complaint, upselling, ads/marketing). Session **`products`** cache and **active processes** are injected each run via pydantic_ai **`instructions`** (dynamic adjunct to system context).
- **Specialized Agents** — Product, Payment Verification, Logistics, Customer Complaint, Upselling, Ads/Marketing.
- **Central Agent** — Coordinates customer, vendor, and logistics; creates orders after payment confirmation; pushes **`inbox:{recipient_id}`**; optional **WhatsApp** relay. Communication history is summarized automatically when it exceeds word limits.
- **Customer outbound polish** — When the central agent's **`recipient`** is **Customer**, a polish agent rewrites the draft using recent customer and vendor-side chat snippets so the text stays short and chat-native (facts preserved).
- **Business Chat Interface** — Vendor/logistics chat using **`get_party_state` / `modify_party_state`** on the single party id; can forward structured replies to **`run_central_agent`**.

**Memory Management**

- **Chat history summarization** — When chat_history exceeds a configurable word limit (`CHAT_HISTORY_SUMMARY_WORD_LIMIT`), older messages are summarized by a small agent. The summary is persisted to `chat_history_summaries` in PostgreSQL. The last N messages (`CHAT_HISTORY_KEEP_LAST_N`) are kept verbatim.
- **Communication history summarization** — Per-process `communication_history` is summarized in-memory (no DB) when it exceeds `COMM_HISTORY_SUMMARY_WORD_LIMIT`.
- **File text cache cap** — Only the last `FILE_TEXT_CACHE_MAX` entries are kept in Redis; older files are available via the `conversation_uploaded_files` table.
- **Products cache TTL** — Cached product query results expire after `PRODUCTS_CACHE_TTL_HOURS` hours and are evicted on the next customer turn.

---

## 2. Data Flow & State

### Redis: customer–vendor key `{user_id}:{vendor_id}`

| Field | Description |
|-------|-------------|
| `chat_history` | Pydantic AI message history (customer channel). Summarized when large. |
| `products` | Cached product search results (per-query key, with `_ts` timestamp for TTL eviction). |
| `products_discussed` | Canonical product names mentioned this session. |
| `processes` | Per-product workflow dict keyed by UUID `process_id`. |
| `business_information` | Cached vendor details (name, tier, bank info, contacts). |
| `receipt_data` | Extracted receipt content for payment verification. |
| `receipt_texts` | Raw receipt transcript strings. |
| `uploaded_files` | Processed file metadata refs (file_id, filename, type, description). |
| `file_text_cache` | Last N extracted text entries by file_id (capped to `FILE_TEXT_CACHE_MAX`). |

### Process structure (inside `processes[process_id]`)

| Field | Description |
|-------|-------------|
| `task_type` | `TaskType` value (Product Enquiry, Payment Verification, Logistics Coordination, Complaint, Unknown). |
| `product_name` | Product this process concerns. |
| `order_id` | UUID of the DB order (set after order creation). |
| `order_number` | Human-readable order number (e.g. ORD-20260404-1234). |
| `quantity` | Order quantity. |
| `customer_address` | Delivery address. |
| `status` | Order status (pending, payment_verified, shipped, delivered, cancelled). |
| `tracking_number` | Logistics tracking number. |
| `communication_history` | Multi-party message log for central agent (auto-summarized). |
| `finished_tasks` | List of completed milestone strings. |

### Redis: party key `{vendor_id}` or `{logistic_id}`

| Field | Description |
|-------|-------------|
| `chat_history` | Business or logistics operator chat with the assistant. |

### Inbox: `inbox:{recipient_id}`

Payload: `message`, `sender`, `recipient`, `process_id`, `task_type`, and when relevant `customer_id`, `product_name`, `order_id`, `business_id`. Vendor/logistics messages are prefixed with `[Customer: … | Product: … | Process: … | Task: … | Order: …]`.

### PostgreSQL

| Table | Purpose |
|-------|---------|
| `businesses` | Vendor profiles, tier, bank details, social handles, product schema. |
| `products` | Catalog (per-business), stock, attributes (JSONB), full-text search. |
| `users` | Customer profiles, delivery address. |
| `orders` | Created only after payment confirmation. Status lifecycle: pending → payment_verified → shipped → delivered. |
| `transactions` | Payment records (pending → verified). |
| `conversation_uploaded_files` | Persisted file uploads (URL, content type, extracted text). |
| `chat_history_summaries` | Running chat summary per user-vendor pair. |

---

## 3. Stage-by-Stage Workflow

### Stage 1: Customer entry

```
Customer → POST /api/v1/customer/chat
         → user_chat_interface.chat()
         → get_user_state(user_id, vendor_id)
         → (optional) process_uploaded_files() for receipts/images
         → evict stale product cache (>TTL)
         → cap file_text_cache
         → maybe_summarize_chat_history() → persist summary to DB
         → run_conversational_agent(
               user_message, chat_history, user_id, vendor_id, user_state,
               business_name, order_context_summary, receipt_data, …
            )
```

The **conversational agent** chooses **tools** (handoffs to product, payment, logistics, complaint, upsell, ads/marketing) and returns natural language. **`order_context_summary`** is derived from `user_state["processes"]`.

---

### Stage 2: Product & purchase

Specialist **`run_product_agent`** handles catalog search, payment info, vendor notify. Results populate **`user_state["products"]`** with a `_ts` timestamp, which is formatted into **instructions** on each conversational turn.

---

### Stage 3: Payment verification

**Payment Verification Agent** — receipt / link checks, vendor confirmation, **`notify_central_payment_confirmed`** → builds **`CentralAgentInput`** with `process_id` + `task_type` and calls **`run_central_agent`**.

---

### Stage 4: Central agent & orders

**Central agent** outputs structured **`reasoning`**, **`next_step`**, **`message`**, **`recipient`**, **`sender`**, **`finished_tasks`**. Tools include **`create_order`**, **`get_order_info`**, **`update_order_status`**, **`mark_task_finished`**, **`get_delivery_address`**, **`get_logistics_info`**, **`get_contact_info`**, **`get_business_bank_details`**.

Before the agent runs, `communication_history` is summarized via `maybe_summarize_comm_history()` if it exceeds word limits.

**Customer outbound:** if **`recipient`** is **Customer**, **`polish_central_message_for_customer`** runs on the draft.

**Persistence after send:**

- To **customer:** `append_inbox_turn_to_customer_pair(customer_id, business_id, msg)`
- To **vendor / logistics:** `append_inbox_turn_to_party_state(party_id, msg)`

**Critical rule:** **`create_order`** only after payment confirmation.

---

### Stage 5: Complaint handling

**Customer Complaint Agent** — empathetic de-escalation; can **`notify_central_agent`** to escalate to vendor/logistics via central coordination (uses `TaskType.COMPLAINT`).

---

### Stage 6: Upselling & Post-purchase Marketing

- **Upselling Agent** — triggered when enquired product is unavailable. Searches for alternates/complements from same store (and cross-store if tier allows).
- **Ads/Marketing Agent** — triggered post-purchase when logistics is sorted. Suggests complementary products; optional cross-sell if tier permits.

---

### Stage 7: Logistics (customer channel)

**Logistics agent** (via conversational tools) uses **`processes`** / **`order_id`** and can **`notify_central_agent`** so the central agent routes to vendor or logistics.

---

### Stage 8: Vendor / logistics reply

```
POST /api/v1/business/chat or /api/v1/logistics/chat
  → business_chat()
  → get_party_state(vendor_id | logistic_id)
  → business_chat_agent extracts reply_context from inbox-shaped history
  → if for_central_agent: ensure_central_process + create_structured_input(...)
    + run_central_agent(..., user_state from get_user_state(customer_id, vendor_id))
  → modify_party_state(party_id, user_state)
```

---

### Stage 9: Delivery & completion

Central agent coordinates status updates, **`finished_tasks`**, and inbox pushes. **`update_order_status`** reflects shipped/delivered when vendor/logistics confirm.

---

## 4. API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/customer/chat` | Customer message (JSON or FormData with files) |
| `GET /api/v1/customer/inbox/{user_id}` | Poll customer inbox |
| `POST /api/v1/business/chat` | Vendor message |
| `GET /api/v1/business/inbox/{vendor_id}` | Poll vendor inbox |
| `POST /api/v1/logistics/chat` | Logistics message |
| `GET /api/v1/logistics/inbox/{logistic_id}` | Poll logistics inbox |
| `POST /api/v1/session/clear` | Clears pair state, party state, and inbox keys |

---

## 5. Configuration Constants

| Constant | Default | Description |
|----------|---------|-------------|
| `CHAT_HISTORY_SUMMARY_WORD_LIMIT` | 2048 | Summarize chat_history when word count exceeds this. |
| `CHAT_HISTORY_KEEP_LAST_N` | 20 | Keep last N messages verbatim after summarization. |
| `COMM_HISTORY_SUMMARY_WORD_LIMIT` | 1024 | Summarize per-process communication_history when exceeded. |
| `COMM_HISTORY_KEEP_LAST_N` | 10 | Keep last N comm entries after summarization. |
| `FILE_TEXT_CACHE_MAX` | 5 | Max file_text_cache entries in Redis. |
| `PRODUCTS_CACHE_TTL_HOURS` | 12 | Product cache entry expiry in hours. |

---

## 6. Agent Interaction Diagram

```
                    ┌─────────────────────┐
                    │   Customer Chat     │
                    │  (user_chat)        │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Conversational Agent │
                    │ (+products/processes │
                    │  in instructions)    │
                    └──────────┬──────────┘
       ┌──────────┬────────────┼────────────┬──────────┐
       │          │            │            │          │
    Product   Payment     Logistics    Complaint   Upsell /
     tools    tools        tools        tools     Ads-Mktg
       │          │            │            │          │
       └──────────┴────────────┼────────────┴──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Central Agent     │
                    │ (+ polish if →      │
                    │  Customer)          │
                    │ push_to_inbox       │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
         Customer           Vendor         Logistics
         (inbox +          (party key      (party key
          pair state)       + inbox)        + inbox)
              │                │                │
              └────────────────┴────────────────┘
                               │
                    Business / Logistics chat
                    → back to Central Agent
```

---

## 7. WhatsApp & `get_contact`

When **`whatsapp.send_message`** is used after the central agent run:

| Entity | Resolves to |
|--------|-------------|
| **Customer** | Customer phone or id |
| **Vendor** | Business phone or id |
| **Logistics** | Logistics phone or id |
| **Agent** | **Same as vendor** — the automated coordinator uses the business line |

If **sender** and **recipient** resolve to the **same** address, the send is **skipped** to avoid a self-message.

---

## 8. What Is Not Yet Done

| Area | Status | Notes |
|------|--------|-------|
| **Payment link verification** | Placeholder | Real gateway integration (Paystack) |
| **Payment link generation** | Placeholder | Product agent |
| **WhatsApp** | Optional | Configure provider; Agent uses vendor identity |
| **Dedicated system WhatsApp number** | Not modeled | Today Agent = business contact |
