"""Message query functions."""

from uuid import UUID

from db.connection import get_db_connection
from db.models.message import Message, MessageSenderType


async def create_message(
    conversation_id: UUID,
    sender_type: MessageSenderType | str,
    content: str,
    is_internal: bool = False,
) -> Message:
    """Create a new message."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO message (conversation_id, sender_type, content, is_internal)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            conversation_id,
            sender_type if isinstance(sender_type, str) else sender_type.value,
            content,
            is_internal,
        )
        return Message(**dict(row))


async def get_message_by_id(message_id: UUID) -> Message | None:
    """Get a message by ID."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow("SELECT * FROM message WHERE id = $1", message_id)
        return Message(**dict(row)) if row else None


async def get_conversation_messages(
    conversation_id: UUID, include_internal: bool = True, limit: int = 100, offset: int = 0
) -> list[Message]:
    """Get all messages for a conversation, optionally excluding internal messages."""
    async with get_db_connection() as conn:
        if include_internal:
            rows = await conn.fetch(
                """
                SELECT * FROM message
                WHERE conversation_id = $1
                ORDER BY timestamp ASC
                LIMIT $2 OFFSET $3
                """,
                conversation_id,
                limit,
                offset,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM message
                WHERE conversation_id = $1 AND is_internal = false
                ORDER BY timestamp ASC
                LIMIT $2 OFFSET $3
                """,
                conversation_id,
                limit,
                offset,
            )
        return [Message(**dict(row)) for row in rows]


async def get_public_messages(
    conversation_id: UUID, limit: int = 100, offset: int = 0
) -> list[Message]:
    """Get only public (non-internal) messages for a conversation."""
    return await get_conversation_messages(
        conversation_id, include_internal=False, limit=limit, offset=offset
    )


async def update_message(message_id: UUID, **updates) -> Message | None:
    """Update a message with arbitrary fields."""
    if not updates:
        return await get_message_by_id(message_id)

    # Build dynamic UPDATE query
    set_clauses = ", ".join([f"{key} = ${i + 2}" for i, key in enumerate(updates.keys())])
    values = [message_id] + list(updates.values())

    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE message
            SET {set_clauses}
            WHERE id = $1
            RETURNING *
            """,
            *values,
        )
        return Message(**dict(row)) if row else None


async def delete_message(message_id: UUID) -> bool:
    """Delete a message."""
    async with get_db_connection() as conn:
        result = await conn.execute("DELETE FROM message WHERE id = $1", message_id)
        return result == "DELETE 1"
