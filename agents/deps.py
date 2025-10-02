"""Agent dependencies (context passed to tools)."""

from dataclasses import dataclass
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
