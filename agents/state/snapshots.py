"""State snapshot functionality for pause/resume workflows.

Implements Pydantic AI state persistence pattern for interrupting and resuming
conversations at specific points.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class StateSnapshot(BaseModel):
    """Represents a point-in-time snapshot of conversation state.

    Used for pause/resume workflows where we need to capture the exact state
    at the moment of interruption.
    """

    id: UUID
    conversation_id: UUID
    business_id: UUID

    # Agent execution state at snapshot time
    active_agent_id: UUID | None
    active_tool: str | None
    tool_arguments: dict[str, Any] | None = None

    # Full conversation state
    state_data: dict[str, Any]

    # Snapshot metadata
    reason: str  # e.g., "waiting_for_payment", "user_requested_pause"
    created_at: datetime

    # Resume tracking
    resumed_at: datetime | None = None
    resumed_by: str | None = None  # "user" | "system" | "agent"


class SnapshotManager:
    """Manages creation and restoration of state snapshots."""

    async def create(
        self,
        conversation_id: UUID,
        business_id: UUID,
        state_data: dict[str, Any],
        reason: str,
        active_agent_id: UUID | None = None,
        active_tool: str | None = None,
        tool_arguments: dict[str, Any] | None = None,
    ) -> StateSnapshot:
        """Create a new state snapshot.

        Args:
            conversation_id: ID of the conversation
            business_id: ID of the business
            state_data: Full conversation state as dict
            reason: Why this snapshot was created
            active_agent_id: Agent that was active at snapshot time
            active_tool: Tool that was executing at snapshot time
            tool_arguments: Arguments to the active tool

        Returns:
            Created snapshot
        """
        # TODO: Implement snapshot creation
        # INSERT into conversation_state_snapshots table
        raise NotImplementedError("Snapshot creation not yet implemented")

    async def get(self, snapshot_id: UUID) -> StateSnapshot | None:
        """Retrieve a snapshot by ID.

        Args:
            snapshot_id: ID of the snapshot

        Returns:
            Snapshot or None if not found
        """
        # TODO: Implement snapshot retrieval
        raise NotImplementedError("Snapshot retrieval not yet implemented")

    async def get_latest_for_conversation(self, conversation_id: UUID) -> StateSnapshot | None:
        """Get the most recent snapshot for a conversation.

        Args:
            conversation_id: ID of the conversation

        Returns:
            Latest snapshot or None if no snapshots exist
        """
        # TODO: Implement latest snapshot retrieval
        # SELECT * FROM conversation_state_snapshots
        # WHERE conversation_id = $1
        # ORDER BY created_at DESC
        # LIMIT 1
        raise NotImplementedError("Latest snapshot retrieval not yet implemented")

    async def mark_resumed(self, snapshot_id: UUID, resumed_by: str = "user") -> None:
        """Mark a snapshot as resumed.

        Args:
            snapshot_id: ID of the snapshot
            resumed_by: Who/what resumed the conversation
        """
        # TODO: Implement snapshot resume marking
        # UPDATE conversation_state_snapshots
        # SET resumed_at = NOW(), resumed_by = $1
        # WHERE id = $2
        raise NotImplementedError("Snapshot resume marking not yet implemented")

    async def list_for_conversation(
        self, conversation_id: UUID, limit: int = 10
    ) -> list[StateSnapshot]:
        """List all snapshots for a conversation.

        Args:
            conversation_id: ID of the conversation
            limit: Maximum number of snapshots to return

        Returns:
            List of snapshots, ordered by creation time (newest first)
        """
        # TODO: Implement snapshot listing
        raise NotImplementedError("Snapshot listing not yet implemented")
