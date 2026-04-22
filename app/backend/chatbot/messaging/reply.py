# Channel-agnostic agent output. Agents emit plain text — choosing UI
# primitives (buttons, lists, flows, templates) is a dispatcher concern, not an
# agent one. Keeps prompts simple and prevents accidental coupling to WhatsApp.

from __future__ import annotations

from pydantic import BaseModel


class Reply(BaseModel):
    text: str
