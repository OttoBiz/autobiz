"""Agent dependencies (context passed to tools)."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass
class AgentDeps:
    """
    Dependencies passed to agent tools via RunContext.

    Contains the context needed for tools to operate within a specific
    business and conversation.
    """

    business_id: UUID
    conversation_id: UUID | None = None
    customer_id: UUID | None = None
    channel: str | None = None  # "whatsapp", "sms", "email" etc.
    current_agent_id: UUID | None = None
    current_agent_role: str | None = None
    context_variables: dict[str, Any] = field(default_factory=dict)
