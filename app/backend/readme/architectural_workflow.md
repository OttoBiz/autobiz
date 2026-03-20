# Architectural Workflow

A comprehensive overview of the Autobiz backend from the first conversation stage through successful logistic delivery.

---

## 1. System Overview

The backend is a multi-agent chatbot system that automates business operations across **customers**, **vendors (businesses)**, and **logistics**. State is keyed by `customer_id:vendor_id` in Redis, ensuring each customer–business conversation has isolated context.

**Core components:**
- **User Chat Interface** – Entry point for customer messages; routes to specialized agents
- **Routing Agent** – Classifies conversation stage and extracts product/order context
- **Specialized Agents** – Product, Payment Verification, Logistics, Customer Complaint
- **Central Agent** – Orchestrates multi-party communication, creates orders, tracks tasks
- **Business Chat Interface** – Handles vendor/logistics responses with reply context

---

## 2. Data Flow & State

### Redis State (Key: `{user_id}:{vendor_id}`)

| Field | Description |
|-------|-------------|
| `chat_history` | Pydantic AI message history for the conversation |
| `products` | Cached product search results |
| `processes` | Per-product workflow state: `{product_name: {order_id, order_number, customer_address, status}}` |
| `finished_tasks` | List of completed activities (payment verified, order created, etc.) |
| `central_communication_history` | Multi-party messages for central agent context |
| `business_information` | Cached vendor details |
| `receipt_data` | Extracted receipt content for payment verification |
| `uploaded_files` | Processed file metadata |

### Inbox (Key: `inbox:{recipient_id}`)

Messages pushed to vendors/logistics include `message`, `sender`, `recipient`, and context: `customer_id`, `product_name`, `order_id` for reply association.

### PostgreSQL

- **orders** – Created only after payment confirmation
- **transactions** – Payment records
- **products**, **businesses**, **users** – Core entities

---

## 3. Stage-by-Stage Workflow

### Stage 1: Entry & Routing

```
Customer → POST /api/v1/customer/chat
         → user_chat_interface.chat()
         → get_user_state(user_id, vendor_id)
         → (optional) process_uploaded_files() for receipts/images
         → route_conversation(message, chat_history, business_id, user_id, business_name, order_context)
```

**Routing Agent** determines:
- `stage`: Product Enquiry | Product purchase | Payment verification | Logistics | Ads Marketing | Customer complaint/Feedback | General
- `product_name`, `product_category`, `order_id` (from `order_context` when available)
- `intent`: enquiry | purchase
- `confidence`: 0.0–1.0

`order_context` is built from `user_state["processes"]` as `"Product A -> order_id_1, Product B -> order_id_2"` so routing can pass `order_id` for delivery/tracking questions.

---

### Stage 2: Product Enquiry / Product Purchase

```
stage ∈ {Product Enquiry, Product purchase}
  → run_product_agent(customer_message, product_name, product_category, intent, user_id, business_id, user_state)
```

**Product Agent** tools:
- `get_product_info(product_name?, category?)` – Fetches products from DB
- `get_business_payment_info()` – Bank details for transfer
- `fetch_payment_link()` – Payment gateway link (placeholder)
- `notify_vendor(message)` – Sends to central agent → vendor inbox
- `upsell_products()` – Cross-sell when product not found

Product results are cached in `user_state["products"]`. When the customer decides to purchase, the flow moves to payment verification.

---

### Stage 3: Payment Verification

```
stage == "Payment verification" OR receipt_data present
  → run_verification_agent(..., product_name, receipt_data, order_id)
```

**Payment Verification Agent** tools:
- `verify_payment_link(transaction_reference)` – Checks payment gateway (Paystack placeholder)
- `notify_vendor_for_confirmation()` – Asks vendor to confirm receipt payment
- `notify_central_payment_confirmed(product_name, amount, delivery_address?)` – **Triggers order creation**

**Flow:**
1. **Receipt**: Agent notifies vendor → vendor confirms in business chat → agent calls `notify_central_payment_confirmed`
2. **Payment link**: Agent calls `verify_payment_link` → on success, calls `notify_central_payment_confirmed`

`notify_central_payment_confirmed` builds `CentralAgentInput` and calls `run_central_agent()` with `user_state` so the central agent has full context.

---

### Stage 4: Order Creation (Central Agent)

```
Payment confirmed
  → run_central_agent(CentralAgentInput(sender="Agent", recipient="Agent", message="Payment confirmed. Create order: ..."))
  → Central agent uses create_order tool
```

**Central Agent** tools:
- `create_order(product_name, total_amount, delivery_address?, ...)` – Inserts into `orders` table, updates `processes[product_name]` with `order_id`, `order_number`, `status`
- `get_order_info(order_id?, order_number?)` – Reads from DB or processes cache
- `mark_task_finished(task_description)` – Appends to `finished_tasks`
- `get_delivery_address(product_name?)` – From processes or user profile
- `get_logistics_info()` – Lists logistics companies
- `get_contact_info(entity)` – Customer, Vendor, or Logistics contact details

**Critical rule:** Orders are created **only** after payment confirmation (verbal from vendor or verified via payment link).

---

### Stage 5: Logistics Coordination

```
stage == "Logistics"
  → run_logistics_agent(..., product_name, order_id from routing)
```

**Logistics Agent** tools:
- `get_order_for_product(product_name?)` – Reads `order_id` from `processes`
- `get_product_from_cache()` – Identifies product from cached results
- `notify_central_agent(message, recipient, order_id?)` – Sends to Vendor or Logistics with order context

The agent uses `order_id` from processes (or routing) when notifying the central agent, so the central agent can update the correct order and route responses to the right customer.

---

### Stage 6: Multi-Party Communication (Vendor / Logistics Response)

```
Vendor/Logistics receives inbox message with context (customer_id, product_name, order_id)
  → Frontend displays "[Re: customer_id · product_name · order_id] [From Agent] message"
  → User clicks message → sets reply context
  → User sends "Yes, confirmed" (or similar)
  → POST /api/v1/business/chat or /api/v1/logistics/chat
  → business_chat(BusinessRequest with user_id=customer_id, product_name, order_id)
```

**Business Chat Interface:**
- When `reply_context` (customer_id, product_name, order_id) is present, builds `CentralAgentInput` from request and routes to `run_central_agent` with `user_state = get_user_state(customer_id, vendor_id)`
- Central agent receives vendor/logistics message in the correct customer–vendor thread
- Central agent can create order, update status, push to customer inbox, etc.

**Inbox push** from central agent includes `customer_id`, `product_name`, `order_id` so vendors can associate responses with the right thread.

---

### Stage 7: Delivery & Completion

- **Central agent** coordinates between vendor, logistics, and customer
- **Logistics agent** helps customers track deliveries and provide addresses
- **Order status** can be updated via `update_order_status(order_id, status, tracking_number?, logistic_id?)` (e.g. `shipped`, `delivered`)
- **finished_tasks** tracks completed steps: payment verified, order created, delivery arranged, etc.

---

## 4. API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/customer/chat` | Customer message (JSON or FormData with files) |
| `GET /api/v1/customer/inbox/{user_id}` | Poll customer inbox (order updates, delivery notifications) |
| `POST /api/v1/business/chat` | Vendor message (with optional reply context) |
| `GET /api/v1/business/inbox/{vendor_id}` | Poll vendor inbox |
| `POST /api/v1/logistics/chat` | Logistics message |
| `GET /api/v1/logistics/inbox/{logistic_id}` | Poll logistics inbox |
| `GET /api/v1/logistics/orders/{order_id}/tracking` | Order tracking (status, tracking_number, delivery details) |

---

## 5. Agent Interaction Diagram

```
                    ┌─────────────────┐
                    │  Customer Chat  │
                    │  (user_chat)    │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Routing Agent   │
                    │ (stage, product,│
                    │  order_id)      │
                    └────────┬────────┘
         ┌───────────────────┼───────────────────┐
         │                   │                   │
    Product Enquiry    Payment Verify      Logistics
         │                   │                   │
    ┌────▼────┐        ┌─────▼─────┐       ┌─────▼─────┐
    │ Product │        │ Payment   │       │ Logistics │
    │ Agent   │        │ Agent     │       │ Agent     │
    └────┬────┘        └─────┬─────┘       └─────┬─────┘
         │                   │                    │
         │         notify_central_payment_confirmed│
         │                   │                    │
         └───────────────────┼────────────────────┘
                             │
                    ┌────────▼────────┐
                    │ Central Agent    │
                    │ create_order     │
                    │ get_order_info   │
                    │ push_to_inbox    │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
         Customer        Vendor        Logistics
         (inbox)         (inbox)        (inbox)
              │              │              │
              │     Business Chat (reply)   │
              │              │              │
              └──────────────┴──────────────┘
                             │
                    back to Central Agent
```

---

## 6. What Is Not Yet Done

| Area | Status | Notes |
|------|--------|-------|
| **Payment link verification** | Placeholder | `verify_payment_link` needs Paystack (or similar) API integration |
| **Payment link generation** | Placeholder | `fetch_payment_link` in product agent not implemented |
| **WhatsApp integration** | Optional | `whatsapp.send_message` called but may not be configured |
| **End-to-end tests** | Sparse | Test conversations have TODO for actual agent calls |
