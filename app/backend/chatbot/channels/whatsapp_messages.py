"""Pydantic models + builders for WhatsApp Cloud API outbound messages.

Each model produces the JSON body that the `/messages` endpoint expects via
`to_whatsapp_payload()`. The shared envelope fields (`messaging_product`,
`recipient_type`, `to`, `type`) are filled in here; the channel layer adds the
recipient phone via `WhatsappChannel.send_*`.

Reference shapes:
- Buttons / List: https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
- Flow:           https://developers.facebook.com/docs/whatsapp/flows/reference/flowsapi
- Template:       https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages

TODO: Dynamic Flows that use a Flow Data Endpoint (encrypted server-side
data exchange) are intentionally out of scope here. The `Flow` model below
covers the simple "navigate" action with a static `data` payload, which is
sufficient for confirmation prompts and short info requests. Encrypted
data-exchange flows require a registered HTTPS endpoint, key pinning, and
AES-GCM payload decryption — separate task.
"""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.config import config


# ---------------------------------------------------------------------------
# Shared sub-models
# ---------------------------------------------------------------------------


class _Header(BaseModel):
    type: Literal["text"] = "text"
    text: str


class _Body(BaseModel):
    text: str


class _Footer(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# Buttons (interactive.type = "button"): up to 3 reply buttons
# ---------------------------------------------------------------------------


class ReplyButton(BaseModel):
    id: str
    title: str

    def to_action_entry(self) -> dict[str, Any]:
        return {"type": "reply", "reply": {"id": self.id, "title": self.title}}


class ButtonMessage(BaseModel):
    body: str
    buttons: list[ReplyButton]
    header: str | None = None
    footer: str | None = None

    def to_whatsapp_payload(self) -> dict[str, Any]:
        interactive: dict[str, Any] = {
            "type": "button",
            "body": {"text": self.body},
            "action": {"buttons": [b.to_action_entry() for b in self.buttons]},
        }
        if self.header is not None:
            interactive["header"] = {"type": "text", "text": self.header}
        if self.footer is not None:
            interactive["footer"] = {"text": self.footer}
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "type": "interactive",
            "interactive": interactive,
        }


# ---------------------------------------------------------------------------
# Lists (interactive.type = "list"): up to 10 rows across sections
# ---------------------------------------------------------------------------


class ListRow(BaseModel):
    id: str
    title: str
    description: str | None = None

    def to_row_entry(self) -> dict[str, Any]:
        row: dict[str, Any] = {"id": self.id, "title": self.title}
        if self.description is not None:
            row["description"] = self.description
        return row


class ListSection(BaseModel):
    title: str
    rows: list[ListRow]

    def to_section_entry(self) -> dict[str, Any]:
        return {"title": self.title, "rows": [r.to_row_entry() for r in self.rows]}


class ListMessage(BaseModel):
    body: str
    button: str
    sections: list[ListSection]
    header: str | None = None
    footer: str | None = None

    def to_whatsapp_payload(self) -> dict[str, Any]:
        interactive: dict[str, Any] = {
            "type": "list",
            "body": {"text": self.body},
            "action": {
                "button": self.button,
                "sections": [s.to_section_entry() for s in self.sections],
            },
        }
        if self.header is not None:
            interactive["header"] = {"type": "text", "text": self.header}
        if self.footer is not None:
            interactive["footer"] = {"text": self.footer}
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "type": "interactive",
            "interactive": interactive,
        }


# ---------------------------------------------------------------------------
# Flows (interactive.type = "flow")
# ---------------------------------------------------------------------------


class Flow(BaseModel):
    flow_id: str
    flow_token: str
    flow_cta: str
    body: str
    # `screen` is the first screen of the flow that the user lands on.
    screen: str
    header: str | None = None
    footer: str | None = None
    # Optional initial data passed to the screen. Cloud API requires this as
    # a JSON-encoded string inside `flow_action_payload.data`; we serialize
    # in `to_whatsapp_payload()` so callers pass a normal dict.
    data: dict[str, Any] | None = None
    # `draft` is for in-development flows; `published` is for live ones.
    # Cloud API rejects `draft` mode for flows that aren't owned by the same
    # business as the sending number.
    mode: Literal["draft", "published"] = "published"
    # `navigate` opens a screen client-side; `data_exchange` triggers the
    # server endpoint round-trip — not supported here (see module TODO).
    flow_action: Literal["navigate", "data_exchange"] = "navigate"

    def to_whatsapp_payload(self) -> dict[str, Any]:
        action_payload: dict[str, Any] = {"screen": self.screen}
        if self.data is not None:
            # Cloud API requires `data` as a JSON-encoded string, not an object.
            action_payload["data"] = json.dumps(self.data)

        interactive: dict[str, Any] = {
            "type": "flow",
            "body": {"text": self.body},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_token": self.flow_token,
                    "flow_id": self.flow_id,
                    "flow_cta": self.flow_cta,
                    "flow_action": self.flow_action,
                    "flow_action_payload": action_payload,
                    "mode": self.mode,
                },
            },
        }
        if self.header is not None:
            interactive["header"] = {"type": "text", "text": self.header}
        if self.footer is not None:
            interactive["footer"] = {"text": self.footer}
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "type": "interactive",
            "interactive": interactive,
        }


# ---------------------------------------------------------------------------
# Templates (type = "template"): pre-approved out-of-window messages
# ---------------------------------------------------------------------------


class Template(BaseModel):
    name: str
    language: str = "en_US"
    components: list[dict[str, Any]] = Field(default_factory=list)

    def to_whatsapp_payload(self) -> dict[str, Any]:
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "type": "template",
            "template": {
                "name": self.name,
                "language": {"code": self.language},
                "components": self.components,
            },
        }


# ---------------------------------------------------------------------------
# Component helpers — the short prebuilt library agents reach for. Three only.
# ---------------------------------------------------------------------------


def confirm_request(
    question: str, yes_id: str = "yes", no_id: str = "no"
) -> ButtonMessage:
    """Yes/No confirmation prompt rendered as two reply buttons."""
    return ButtonMessage(
        body=question,
        buttons=[
            ReplyButton(id=yes_id, title="Yes"),
            ReplyButton(id=no_id, title="No"),
        ],
    )


def pick_option(prompt: str, options: list[tuple[str, str]]) -> ListMessage:
    """List picker. `options` is a list of `(id, title)` tuples."""
    rows = [ListRow(id=oid, title=title) for oid, title in options]
    return ListMessage(
        body=prompt,
        button="Choose",
        sections=[ListSection(title="Options", rows=rows)],
    )


def request_info(prompt: str, fields: list[str]) -> Flow:
    """Open the standing 'request information' flow with a list of field labels.

    The actual flow definition (screens, validation) lives in WhatsApp Manager
    and is referenced by `FLOW_REQUEST_INFO_ID`. We pass `fields` through as
    initial screen data so the same flow can collect different pieces of info
    depending on context.
    """
    return Flow(
        flow_id=config.FLOW_REQUEST_INFO_ID,
        flow_token=f"request_info:{':'.join(fields)}",
        flow_cta="Provide info",
        body=prompt,
        screen="REQUEST_INFO",
        data={"fields": fields},
    )
