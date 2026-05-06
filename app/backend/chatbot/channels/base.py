import abc
from datetime import datetime
from typing import ClassVar, Literal

from pydantic import BaseModel


class WindowPolicy(BaseModel):
    has_window: bool
    window_hours: int | None
    out_of_window_behavior: Literal["template", "drop", "queue"]


class ChannelIdentity(BaseModel):
    business_id: str
    customer_id: str
    channel: str
    channel_user_id: str
    last_inbound_at: datetime | None
    # Channel-native sender ID for the business (symmetric to
    # `channel_user_id` on the customer side). For WhatsApp this holds the
    # Meta `phone_number_id`; the channel adapter uses it to build the
    # outbound API URL. None for channels that don't need it (e.g. console).
    channel_business_id: str | None = None


class MediaAttachment(BaseModel):
    kind: Literal["image", "audio", "video", "document"]
    url: str | None
    mime_type: str | None
    # Channel-native media id (e.g. WhatsApp media id). The webhook layer uses
    # this to pull bytes from the carrier's media API before stashing a
    # publicly reachable URL in `url`.
    media_id: str | None = None


class InboundMessage(BaseModel):
    identity: ChannelIdentity
    text: str | None
    media: list[MediaAttachment]
    raw: dict
    received_at: datetime
    # Populated when the inbound message originated from an interactive
    # surface (button reply, list reply, or Flow submission). Channel
    # adapters set this; downstream prompt builders can ignore it for plain
    # text messages.
    interactive: dict | None = None


class OutboundMessage(BaseModel):
    identity: ChannelIdentity
    text: str


class Channel(abc.ABC):
    name: ClassVar[str]

    @abc.abstractmethod
    def parse_inbound(self, raw: dict) -> InboundMessage:
        ...

    @abc.abstractmethod
    async def send(self, identity: ChannelIdentity, text: str) -> None:
        ...

    @abc.abstractmethod
    async def send_template(
        self, identity: ChannelIdentity, template: str, vars: dict
    ) -> None:
        ...

    @abc.abstractmethod
    def window_policy(self) -> WindowPolicy:
        ...
