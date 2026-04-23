# Shared dependency models for agent runs. Lives outside any single agent so
# specialized subagents can import without a cycle through `central`.

from typing import Any, List
from uuid import UUID

from pydantic import BaseModel, Field

from backend.chatbot.agents.outbound import OutboundDeps


class AgentDeps(BaseModel):
    customer_id: UUID
    business_id: UUID
    state: dict[str, Any] = Field(default_factory=dict)
    outbound: List[OutboundDeps] = Field(default_factory=list)
    max_depth: int = 3
    current_depth: int = 0
