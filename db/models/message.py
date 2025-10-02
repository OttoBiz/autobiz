from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class MessageSenderType(str, Enum):
    CUSTOMER = "customer"
    AGENT = "agent"
    USER = "user"
    SYSTEM = "system"


class Message(BaseModel):
    id: UUID
    conversation_id: UUID

    # Sender
    sender_type: MessageSenderType

    # Content
    content: str
    is_internal: bool

    # Metadata
    timestamp: datetime
