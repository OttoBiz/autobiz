# Paystack payment flow (Ottobiz)

This document describes how online payments work end-to-end: reference generation, what happens when a customer leaves WhatsApp to pay, and how the backend learns that payment succeeded.

## Data model

- Each **vendor** stores their own Paystack credentials on the `businesses` row:
  - `paystack_public_key` — safe to expose to frontends if you build a custom checkout later.
  - `paystack_secret_key` — **server only**; used to initialize transactions, verify references, and validate webhooks.
- **Platform env** (`PAYSTACK_PUBLIC_KEY` / `PAYSTACK_SECRET_KEY` in `config.py`) is optional and unused by the per-vendor flow described here; the product and verification agents use the **vendor’s** keys from the database.

## Creating a payment (product agent)

1. Customer shows purchase intent in chat (web or WhatsApp).
2. `fetch_payment_link` (in `product_agent.py`) runs when the model calls the tool.
3. The tool:
   - Loads `paystack_secret_key` for `vendor_id` / `business_id`.
   - Resolves **amount** from the tool arguments or from `get_product_by_id` when `product_id` is set.
   - Generates a **unique reference** (e.g. `OBZ` + random hex). Paystack also returns this reference in the initialize response.
   - Calls Paystack **Initialize Transaction** (`POST /transaction/initialize`) with:
     - `amount` in **kobo** (NGN smallest unit): `round(major_amount * 100)`.
     - `email` — from `user_state["customer_email"]` if set, otherwise a stable placeholder `{user_id}@customers.ottobiz.app` (Paystack requires an email).
     - `callback_url` — `{BASE_URL}/api/v1/payments/paystack/callback` (browser redirect after payment).
     - `metadata` — `user_id`, `business_id`, `product_id` (string values) so webhooks can tie the charge back to Redis/chat state.
   - Persists **pending** checkout in Redis user state (`pending_paystack`, `last_paystack_reference`).
   - Writes a **Redis key** `paystack_ref:{reference}` (TTL 7 days) with `user_id`, `business_id`, `product_id`, `amount_major` as a fallback if metadata is missing on the webhook.

Default currency is **`NGN`**; override with env `PAYSTACK_DEFAULT_CURRENCY` if you extend to other Paystack-supported currencies (amount rules differ by currency).

## Where does the payment reference come from?

- **We generate it** when calling Initialize Transaction (`reference` in the API body). Paystack returns the same reference in the response and uses it for the hosted payment page, receipts, and verification.
- The assistant should **tell the customer the reference** along with the link. After payment, the customer can paste that reference in chat so `verify_payment_link` can confirm the charge.

## Customer leaves WhatsApp — how do we know they paid?

Three complementary paths:

### 1. Webhook (recommended, server-to-server)

- Paystack sends **`charge.success`** to your **webhook URL** as JSON `POST`.
- Ottobiz endpoint: **`POST /api/v1/payments/paystack/webhook`** (no rate limiting on this path).
- The handler:
  - Reads raw body and header **`X-Paystack-Signature`**.
  - Resolves **`business_id`** from `data.metadata.business_id` or from Redis `paystack_ref:{reference}`.
  - Loads that vendor’s **`paystack_secret_key`** and verifies the signature (**HMAC SHA512** of raw body with the secret).
  - On success, appends an entry to `user_state["paystack_webhook_confirmed"]` for that `user_id` + `vendor_id`.

**Setup:** In each vendor’s Paystack Dashboard → Settings → API & Webhooks, set the webhook URL to your public `https://<your-domain>/api/v1/payments/paystack/webhook`. Use the **same** secret key as stored in your DB for that vendor (the key that owns the transaction).

### 2. Browser callback (user experience only)

- After payment, Paystack redirects the browser to **`callback_url`** with query params such as `reference` and `trxref`.
- Ottobiz serves **`GET /api/v1/payments/paystack/callback`** as a simple HTML page that shows the reference and tells the user to return to WhatsApp/chat.
- This **does not** replace the webhook: the redirect happens in the user’s browser; your backend still needs the webhook (or an explicit verify call) for reliable automation.

### 3. Verify API (when the user messages again)

- When the customer says they paid or pastes a reference, the **payment verification agent** calls **`verify_payment_link`**.
- That tool:
  - First checks **`paystack_webhook_confirmed`** for that reference (fast path if webhook already ran).
  - Otherwise calls Paystack **`GET /transaction/verify/{reference}`** with the vendor secret.
- On `verified: true`, the agent can call **`notify_central_payment_confirmed`** to drive order creation via the central agent.

## Security notes

- Never log or return `paystack_secret_key` to clients.
- Webhook requests must **fail signature verification** if the secret does not match the account that generated the event.
- `BASE_URL` must be the **public HTTPS URL** Paystack can reach for `callback_url` in production.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `BASE_URL` | Public base URL for `callback_url` (e.g. `https://api.example.com`) |
| `PAYSTACK_DEFAULT_CURRENCY` | Default `NGN`; change if you standardize on another currency |
| `DEBUG` | Unrelated to Paystack verification (real API used when vendor secret exists) |

## Code map

| Piece | Location |
|-------|-----------|
| Initialize / verify / webhook signature | `backend/payments/paystack_client.py` |
| Webhook + browser callback routes | `backend/api/routers/payments.py` |
| Create link + persist pending + Redis ref | `product_agent.fetch_payment_link` |
| Verify + webhook fast path | `payment_verification_agent.verify_payment_link` |
