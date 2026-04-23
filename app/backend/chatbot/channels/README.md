# Channels

A **channel** is a transport adapter that connects a customer-facing surface
(WhatsApp, a browser, a terminal, etc.) to the conversation orchestrator.
Agents emit plain text; the channel decides how to deliver it and how to
parse inbound payloads back into a normalized shape.

This document covers:

1. [The channel contract](#the-channel-contract) — what every channel implements.
2. [Built-in channels](#built-in-channels) — HTTP, WhatsApp, Console.
3. [End-to-end flow](#end-to-end-flow) — what happens between inbound and outbound.
4. [Adding a new channel](#adding-a-new-channel) — recipe for new transports.

---

## The channel contract

Every channel subclasses `Channel` (`base.py`) and implements four methods:

| Method | Purpose |
| --- | --- |
| `parse_inbound(raw: dict) -> InboundMessage` | Convert a raw payload (webhook JSON, POST body, etc.) into a normalized `InboundMessage`. |
| `send(identity, text)` | Deliver plain text to a recipient. |
| `send_template(identity, template, vars)` | Deliver a pre-approved template (WhatsApp needs this outside the 24h session window; other channels can render it as text). |
| `window_policy() -> WindowPolicy` | Declare whether the transport has a session window and what to do when messages fall outside it (`template`, `drop`, or `queue`). |

### Shared data types (`base.py`)

```python
class ChannelIdentity:
    business_id: str        # tenant UUID
    customer_id: str        # customer UUID
    channel: str            # "whatsapp" | "http" | "console" | ...
    channel_user_id: str    # transport-specific address (phone, session id, ...)
    last_inbound_at: datetime | None

class InboundMessage:
    identity: ChannelIdentity
    text: str | None
    media: list[MediaAttachment]
    raw: dict                   # original payload for debugging/replay
    received_at: datetime
    interactive: dict | None    # button reply / list reply / flow submission

class OutboundMessage:
    identity: ChannelIdentity
    text: str
```

### Registry (`registry.py`)

Channels register themselves at import time:

```python
# in your channel module
_channel = MyChannel()
registry.register(_channel)
```

Two lookups are supported:

- `registry.get("http")` — by channel name; used by webhook routers.
- `registry.get_for_customer(business_id, customer_id)` — resolves the
  *most recently active* channel for a customer, via the identity resolver
  wired up by `db/channel_identities.py`. The outbound path (vendor replies,
  coordinator notices) uses this to fan back to wherever the customer last
  spoke to us.

---

## Built-in channels

### HTTP (`http.py`)

The general-purpose channel for web frontends, mobile apps, or any client
that speaks HTTP/JSON. Inbound is a `POST`; outbound is streamed over
Server-Sent Events.

#### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/webhooks/http` | Submit a customer message. |
| `GET`  | `/webhooks/http/stream/{channel_user_id}` | SSE stream of outbound messages addressed to `channel_user_id`. |

#### Inbound payload

```json
{
  "business_id": "5f1e...-uuid",
  "customer_id": "3a47...-uuid",
  "channel_user_id": "session-abc",
  "text": "Hi, where's my order?",
  "interactive": null
}
```

- `business_id` / `customer_id` — UUID strings identifying the tenant and
  the end user in our system. The frontend is expected to mint or fetch
  these (e.g., from a login session).
- `channel_user_id` — the address outbound replies are keyed by. Use a
  stable per-session or per-device id. Defaults to `customer_id` if omitted.
- `text` — user-visible message. Optional when `interactive` is supplied.
- `interactive` — optional dict for structured replies (e.g.,
  `{"type": "button_reply", "id": "confirm_yes"}`). Mirrors the WhatsApp
  shape so agents see the same structure on both channels.

Response: `200 {"ok": true}` once the message is accepted. The reply is
not in this response — listen on the SSE stream instead.

#### Outbound SSE stream

Each event frame carries one reply:

```
data: {"text": "Your order shipped yesterday — arriving Friday."}
```

The server emits a `: ping` comment every 15 s to keep proxies from
reaping idle connections. Clients should ignore comment lines.

#### Minimal frontend integration (JavaScript)

```js
const BACKEND = "http://localhost:8000";
const businessId   = "5f1e...-uuid";
const customerId   = "3a47...-uuid";
const sessionId    = crypto.randomUUID();  // channel_user_id

// 1. Subscribe to replies.
const stream = new EventSource(
  `${BACKEND}/webhooks/http/stream/${sessionId}`
);
stream.onmessage = (ev) => {
  const { text } = JSON.parse(ev.data);
  renderAgentMessage(text);
};

// 2. Send a user message.
async function sendMessage(text) {
  await fetch(`${BACKEND}/webhooks/http`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      business_id: businessId,
      customer_id: customerId,
      channel_user_id: sessionId,
      text,
    }),
  });
}
```

#### Window policy

`has_window=False`. Every send is attempted unconditionally — HTTP has no
carrier-imposed session window. If the browser tab is closed, messages
queue on the server until the same `channel_user_id` reconnects.

---

### WhatsApp (`whatsapp.py`)

Wraps the WhatsApp Cloud API (Meta Graph API v18). Supports plain text,
templates, reply buttons, list messages, and static Flows.

#### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET`  | `/webhooks/whatsapp` | Meta's verification handshake. |
| `POST` | `/webhooks/whatsapp` | Inbound message callbacks from Meta. |

#### Required environment variables

| Var | Purpose |
| --- | --- |
| `VERIFY_TOKEN` | String configured in the Meta app's webhook setup; echoed back during the `GET` verification. |
| `APP_SECRET` | Used to verify the `X-Hub-Signature-256` header on inbound POSTs. If unset, signature verification is skipped (warning logged) — **do not run this way in production**. |
| `PAGE_ACCESS_TOKEN` (or `WHATSAPP_API_KEY`) | Bearer token used to call `graph.facebook.com/v18.0/{phone_number_id}/messages`. |

#### Inbound shape

The channel parses standard Meta webhook payloads:

```json
{
  "entry": [{
    "changes": [{
      "value": {
        "metadata":  { "phone_number_id": "..." },
        "messages":  [{ "from": "2348012345678", "text": { "body": "hi" }, "type": "text" }]
      }
    }]
  }]
}
```

Interactive replies (`button_reply`, `list_reply`, `nfm_reply` — Flow
submissions) are flattened into the `InboundMessage.interactive` field so
agents can react without transport-specific branching.

#### Outbound surfaces

- `channel.send(identity, text)` — plain text.
- `channel.send_template(identity, template, vars)` — template message.
  Required when the customer is outside the 24h service window.
- `channel.send_buttons(identity, ButtonMessage(...))` — up to 3 quick replies.
- `channel.send_list(identity, ListMessage(...))` — list picker.
- `channel.send_flow(identity, Flow(...))` — static Flow (data-endpoint
  Flows are not yet supported; see `whatsapp_messages.py`).

Builder models live in `whatsapp_messages.py`.

#### Window policy

`has_window=True, window_hours=24, out_of_window_behavior="template"` — a
free-form text send to a customer who hasn't messaged us in the last 24 h
will be rejected by Meta; route those replies through `send_template`.

---

### Console (`console.py`)

In-process channel for the smoke-test harness — **not a production
transport**. No HTTP surface. Outbound messages land on `asyncio.Queue`s
that the smoke TUI subscribes to, so end-to-end flows can run without
external services.

Unlike WhatsApp and HTTP, the Console channel does **not** self-register
at import time. Call `install()` explicitly from test code:

```python
from backend.chatbot.channels.console import install
channel = install()  # registers + wires a stub identity resolver
```

The smoke CLI (`cli/cli.py`) and integration tests handle this
automatically.

---

## End-to-end flow

```
  customer → channel.parse_inbound → orchestrator.handle_inbound
                                         │
                                         ├─ inbox.enqueue (Redis)
                                         ├─ central_agent.run
                                         └─ dispatcher.dispatch_to_customer
                                                  │
                                                  └─ channel.send → customer
```

Out-of-band outbound traffic (a vendor replying, the sweeper firing a
timeout, the coordinator posting a proactive notice) enters via
`orchestrator.deliver_system_event(business_id, customer_id, item)` or
`orchestrator.wake_central(...)`. Both paths:

1. Acquire the per-customer inbox lock.
2. Look up the customer's most-recent channel via
   `channel_identities.get_most_recent_identity`.
3. Run `central_agent`, dispatch on that channel, persist history, drain.

The customer always hears us on whatever channel they spoke to us on last
— the orchestrator doesn't need to know HTTP from WhatsApp.

---

## Adding a new channel

1. **Create the channel module** under `app/backend/chatbot/channels/<name>.py`.
   Subclass `Channel`, implement the four required methods, and register at
   import time:

   ```python
   from backend.chatbot.channels import registry
   from backend.chatbot.channels.base import Channel, WindowPolicy

   class SMSChannel(Channel):
       name = "sms"
       def parse_inbound(self, raw): ...
       async def send(self, identity, text): ...
       async def send_template(self, identity, template, vars): ...
       def window_policy(self):
           return WindowPolicy(
               has_window=False, window_hours=None, out_of_window_behavior="drop"
           )

   registry.register(SMSChannel())
   ```

2. **Add a webhook/router** under `app/backend/api/routers/webhooks/<name>.py`.
   Import the channel module (that's what triggers registration), then
   parse inbound payloads and hand them to `orchestrator.handle_inbound`:

   ```python
   import backend.chatbot.channels.sms  # noqa: F401  registers the channel
   from backend.chatbot import orchestrator
   from backend.chatbot.channels import registry

   @router.post("/sms")
   async def sms_inbound(request: Request):
       payload = await request.json()
       msg = registry.get("sms").parse_inbound(payload)
       await orchestrator.handle_inbound(msg)
       return {"ok": True}
   ```

3. **Wire the router** into `app/main.py` via `app.include_router(...)`.

4. **Test it** alongside `test_channels_http.py` /
   `test_channels_whatsapp.py`. Cover `parse_inbound`, `send`, the window
   policy, import-time registration, and the webhook → orchestrator call.

Once registered, the outbound resolution path will find your channel
automatically for any customer whose most-recent `channel_identities` row
points at it — no orchestrator changes needed.
