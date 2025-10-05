"""Conversation state manager following Pydantic AI state persistence patterns.

Handles conversation-centric state management where agents are stateless executors.
State lives in conversations, not in individual agents.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ConversationState(BaseModel):
    """Represents the state of an active conversation.

    Follows Pydantic AI pattern where state is conversation-centric,
    not agent-centric. Agents are stateless executors that operate on this state.
    """

    conversation_id: UUID
    business_id: UUID

    # Current execution context
    current_agent_id: UUID | None = None
    current_tool: str | None = None

    # Collaboration tracking
    handoff_history: list[dict[str, Any]] = []  # Who handed off to whom
    consult_history: list[dict[str, Any]] = []  # Who consulted with whom

    # User-facing state
    waiting_for_user: bool = False
    waiting_reason: str | None = None  # e.g., "payment confirmation", "missing info"

    # Internal state (arbitrary key-value pairs)
    custom_data: dict[str, Any] = {}

    # Metadata
    created_at: datetime
    updated_at: datetime


class StateManager:
    """Manages conversation state persistence and retrieval.

    Provides interface for:
    - Saving/loading conversation state
    - Creating state snapshots
    - Resuming interrupted conversations
    """

    async def get_state(self, conversation_id: UUID) -> ConversationState | None:
        """Retrieve current state for a conversation.

        Args:
            conversation_id: ID of the conversation

        Returns:
            Current conversation state or None if not found
        """
        # TODO: Implement database retrieval
        # Query conversation_state table (to be created in schema)
        raise NotImplementedError("State retrieval not yet implemented")

    async def save_state(self, state: ConversationState) -> None:
        """Persist conversation state.

        Args:
            state: Conversation state to save
        """
        # TODO: Implement database persistence
        # INSERT/UPDATE conversation_state table
        raise NotImplementedError("State persistence not yet implemented")

    async def create_snapshot(self, conversation_id: UUID) -> UUID:
        """Create a snapshot of current conversation state.

        Used for pause/resume workflows where we need to capture exact state
        at interruption point.

        Args:
            conversation_id: ID of the conversation

        Returns:
            Snapshot ID
        """
        # TODO: Implement snapshot creation
        # Save full state copy to conversation_state_snapshots table
        raise NotImplementedError("Snapshot creation not yet implemented")

    async def resume_from_snapshot(self, snapshot_id: UUID) -> ConversationState:
        """Restore conversation state from a snapshot.

        Args:
            snapshot_id: ID of the snapshot to restore

        Returns:
            Restored conversation state
        """
        # TODO: Implement snapshot restoration
        raise NotImplementedError("Snapshot restoration not yet implemented")

    async def add_handoff(
        self,
        conversation_id: UUID,
        from_agent_id: UUID,
        to_agent_id: UUID,
        reason: str,
    ) -> None:
        """Record an agent handoff in conversation state.

        Args:
            conversation_id: Conversation where handoff occurred
            from_agent_id: Agent initiating handoff
            to_agent_id: Agent receiving handoff
            reason: Reason for handoff
        """
        state = await self.get_state(conversation_id)
        if not state:
            raise ValueError(f"No state found for conversation {conversation_id}")

        state.handoff_history.append(
            {
                "from_agent_id": str(from_agent_id),
                "to_agent_id": str(to_agent_id),
                "reason": reason,
                "timestamp": datetime.now().isoformat(),
            }
        )
        state.current_agent_id = to_agent_id
        state.updated_at = datetime.now()

        await self.save_state(state)

    async def add_consult(
        self,
        conversation_id: UUID,
        requesting_agent_id: UUID,
        consulted_agent_id: UUID,
        query: str,
    ) -> None:
        """Record an agent consultation in conversation state.

        Args:
            conversation_id: Conversation where consultation occurred
            requesting_agent_id: Agent requesting consultation
            consulted_agent_id: Agent being consulted
            query: What was being asked
        """
        state = await self.get_state(conversation_id)
        if not state:
            raise ValueError(f"No state found for conversation {conversation_id}")

        state.consult_history.append(
            {
                "requesting_agent_id": str(requesting_agent_id),
                "consulted_agent_id": str(consulted_agent_id),
                "query": query,
                "timestamp": datetime.now().isoformat(),
            }
        )
        state.updated_at = datetime.now()

        await self.save_state(state)
