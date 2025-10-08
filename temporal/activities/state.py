"""State persistence activities for loading/saving conversation state."""

from uuid import UUID

from temporalio import activity

from agents.state.manager import StateManager
from db.connection import get_db_pool
from temporal.models import ConversationState


@activity.defn
async def load_conversation_state(conversation_id: str) -> ConversationState | None:
    """Load conversation state from PostgreSQL.

    This activity loads the current state of a conversation from the database.
    Called by the workflow before executing agent logic.

    Args:
        conversation_id: UUID of the conversation

    Returns:
        ConversationState if found, None otherwise
    """
    activity.logger.info(f"Loading state for conversation {conversation_id}")

    conv_id = UUID(conversation_id)
    pool = await get_db_pool()

    # Create state manager
    state_manager = StateManager()
    state_manager.db_pool = pool

    # Load state
    state = await state_manager.get_state(conv_id)

    if state:
        activity.logger.info(f"State loaded for conversation {conversation_id}")
    else:
        activity.logger.info(f"No state found for conversation {conversation_id}")

    return state


@activity.defn
async def save_conversation_state(state_dict: dict) -> None:
    """Save conversation state to PostgreSQL.

    This activity persists the current state of a conversation to the database.
    Called by the workflow after agent execution or state changes.

    Args:
        state_dict: Serialized ConversationState
    """
    activity.logger.info(f"Saving state for conversation {state_dict.get('conversation_id')}")

    pool = await get_db_pool()

    # Deserialize state
    state = ConversationState(**state_dict)

    # Create state manager
    state_manager = StateManager()
    state_manager.db_pool = pool

    # Save state
    await state_manager.save_state(state)

    activity.logger.info(f"State saved for conversation {state.conversation_id}")


@activity.defn
async def create_state_snapshot(conversation_id: str) -> str:
    """Create a snapshot of conversation state for pause/resume workflows.

    Args:
        conversation_id: UUID of the conversation

    Returns:
        Snapshot ID as string
    """
    activity.logger.info(f"Creating state snapshot for conversation {conversation_id}")

    conv_id = UUID(conversation_id)
    pool = await get_db_pool()

    # Create state manager
    state_manager = StateManager()
    state_manager.db_pool = pool

    # Create snapshot
    snapshot_id = await state_manager.create_snapshot(conv_id)

    activity.logger.info(f"Snapshot {snapshot_id} created for conversation {conversation_id}")

    return str(snapshot_id)


@activity.defn
async def resume_from_snapshot(snapshot_id: str) -> dict:
    """Resume conversation state from a snapshot.

    Args:
        snapshot_id: UUID of the snapshot

    Returns:
        Serialized ConversationState
    """
    activity.logger.info(f"Resuming from snapshot {snapshot_id}")

    snap_id = UUID(snapshot_id)
    pool = await get_db_pool()

    # Create state manager
    state_manager = StateManager()
    state_manager.db_pool = pool

    # Resume from snapshot
    state = await state_manager.resume_from_snapshot(snap_id)

    activity.logger.info(
        f"State resumed from snapshot {snapshot_id} for conversation {state.conversation_id}"
    )

    return state.model_dump()
