"""Agent output models for structured responses.

Agents return typed outputs instead of plain strings, enabling clean
separation between agent logic and executor control flow.

See docs/architecture/STRUCTURED_OUTPUT.md for detailed rationale.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class MessageResponse(BaseModel):
    """Standard response to send back to customer.

    This is the default output type for most agent interactions.
    """

    type: Literal["message"] = "message"
    content: str
    metadata: dict[str, Any] = {}


class HandoffResponse(BaseModel):
    """Agent requests handoff to another agent.

    Used when agent needs to transfer conversation ownership to a specialist.
    Executor handles the actual handoff - no tool response goes back to agent.

    Examples:
    - WRITE operations: "Process this refund" → refund-agent
    - Complex GET: "Design enterprise solution" → architect-agent
    - Customer request: "I want to speak to sales" → sales-agent
    """

    type: Literal["handoff"] = "handoff"
    target_agent_role: str
    reason: str
    context_summary: str
    priority: Literal["low", "medium", "high"] = "medium"


class PauseResponse(BaseModel):
    """Agent requests pause until external event occurs.

    Used for workflows that need to wait for external triggers:
    - Payment confirmation (e-commerce)
    - Document upload (verification)
    - Shipping callbacks (tracking updates)
    - Scheduled follow-ups (reminders)

    The conversation is paused and will resume when the trigger event occurs.
    """

    type: Literal["pause"] = "pause"
    content: str  # Message to send to customer
    reason: str  # Internal reason for pause (for tracking)
    resume_trigger: Literal["payment_confirmed", "document_uploaded", "webhook", "scheduled"]
    resume_data: dict[str, Any] = {}  # Data needed to resume conversation
    scheduled_resume_at: datetime | None = None  # For scheduled follow-ups


class MessageContent(BaseModel):
    """Individual message content for multi-message responses."""

    content: str
    media_url: str | None = None
    media_type: Literal["image", "video", "document"] | None = None


class MultiMessageResponse(BaseModel):
    """Send multiple messages sequentially.

    Used when agent needs to send distinct messages in sequence:
    - Step-by-step instructions
    - Product showcase with images
    - Progressive disclosure (avoid wall of text)

    Note: This is optional - may not be needed if channel layer
    handles message formatting and media attachments.
    """

    type: Literal["multi_message"] = "multi_message"
    messages: list[MessageContent]
    delay_between_ms: int = 1000  # Delay between messages (natural typing feel)


# Union type for all possible agent outputs
AgentOutput = MessageResponse | HandoffResponse | PauseResponse | MultiMessageResponse
