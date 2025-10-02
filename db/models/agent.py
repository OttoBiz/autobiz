from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class Agent(BaseModel):
    id: UUID
    business_id: UUID

    # Profile
    name: str
    avatar_url: str | None = None
    personality: str | None = None
    tone: str | None = None

    # System Prompt & Behavior
    system_prompt: str
    greeting_message: str | None = None
    conversation_rules: dict

    # Channels
    channels: dict

    # Metadata
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
