from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class Agent(BaseModel):
    id: UUID
    business_id: UUID

    # Profile
    name: str  # Display name: "Legal Assistant Sarah"
    key: str  # System identifier/routing key: "legal"

    # System Prompt & Behavior
    system_prompt: str

    # Multi-agent configuration
    tool_groups: list[str]  # ["catalog", "customers", "conversations", "collab"]
    subagents: list[str]  # ["legal", "support"] - agent keys this agent can transfer to

    # Channels
    channels: dict

    # Metadata (optional fields for prompt building)
    # personality, tone, greeting_message, avatar_url, conversation_rules
    metadata: dict

    # Status
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
