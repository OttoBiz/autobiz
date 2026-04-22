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


class MediaAttachment(BaseModel):
    kind: Literal["image", "audio", "video", "document"]
    url: str | None
    mime_type: str | None


class InboundMessage(BaseModel):
    identity: ChannelIdentity
    text: str | None
    media: list[MediaAttachment]
    raw: dict
    received_at: datetime


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
