"""Agent dependencies (context passed to tools)."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from agents.executor import AgentExecutor


@dataclass
class AgentDeps:
    """
    Dependencies passed to agent tools via RunContext.

    Contains the context needed for tools to operate within a specific
    business and conversation.
    """

    executor: "AgentExecutor | None" = None
    business_id: UUID | None = None
    conversation_id: UUID | None = None
    customer_id: UUID | None = None
    channel: str | None = None  # "whatsapp", "sms", "email" etc.
    current_agent_id: UUID | None = None
    current_agent_role: str | None = None
    context_variables: dict[str, Any] = field(default_factory=dict)
