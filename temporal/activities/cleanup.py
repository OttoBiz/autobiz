"""Cleanup activities for conversation workflows."""

from datetime import datetime, timezone
from uuid import UUID

from temporalio import activity

from db.connection import get_db_pool


@activity.defn
async def archive_conversation(conversation_id: str) -> None:
    """Archive a conversation after timeout or completion.

    Updates conversation status to 'archived' and records the archival timestamp.

    Args:
        conversation_id: UUID of the conversation to archive
    """
    activity.logger.info(f"Archiving conversation {conversation_id}")

    conv_id = UUID(conversation_id)
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE conversations
            SET
                status = 'archived',
                updated_at = $1
            WHERE id = $2
            """,
            datetime.now(timezone.utc),
            conv_id,
        )

    activity.logger.info(f"Conversation {conversation_id} archived successfully")
