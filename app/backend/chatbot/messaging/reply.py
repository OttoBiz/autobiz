# Single shape, optional fields — agents stay channel-agnostic; the dispatcher
# routes each populated field to the right channel-bound primitive.

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Button(BaseModel):
    id: str
    title: str


class ListRow(BaseModel):
    id: str
    title: str
    description: str | None = None


class ListSection(BaseModel):
    title: str
    rows: list[ListRow]


class FlowRef(BaseModel):
    flow_id: str
    flow_token: str
    flow_cta: str
    body: str
    screen: str
    data: dict[str, Any] | None = None


class TemplateRef(BaseModel):
    name: str
    language: str = "en_US"
    components: list[dict[str, Any]] = Field(default_factory=list)


class OutboundReply(BaseModel):
    text: str | None = None
    buttons: list[Button] | None = None
    list_sections: list[ListSection] | None = None
    list_button_text: str | None = None
    flow: FlowRef | None = None
    template: TemplateRef | None = None
    media_url: str | None = None
    expect_reply: bool = False
    reply_to_id: str | None = None
