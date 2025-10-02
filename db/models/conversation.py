from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class ConversationChannel(str, Enum):
    WHATSAPP = "whatsapp"
    WEBCHAT = "webchat"
    SMS = "sms"
    EMAIL = "email"


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class Conversation(BaseModel):
    id: UUID
    customer_id: UUID | None = None
    business_id: UUID

    # Channel & Status
    channel: ConversationChannel
    status: ConversationStatus

    # Human-in-the-loop
    assigned_to_user_id: UUID | None = None
    escalated_at: datetime | None = None

    # Training data
    feedback_score: int | None = None
    business_notes: str | None = None

    # Metadata
    metadata: dict

    created_at: datetime
    updated_at: datetime
