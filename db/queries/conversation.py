"""Conversation query functions."""

from datetime import datetime
from uuid import UUID

from db.connection import get_db_connection
from db.models.conversation import Conversation, ConversationChannel, ConversationStatus


async def create_conversation(
    business_id: UUID,
    channel: ConversationChannel | str,
    customer_id: UUID | None = None,
    metadata: dict | None = None,
) -> Conversation:
    """Create a new conversation."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO conversation (customer_id, business_id, channel, metadata)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            customer_id,
            business_id,
            channel if isinstance(channel, str) else channel.value,
            metadata or {},
        )
        return Conversation(**dict(row))


async def get_conversation_by_id(conversation_id: UUID) -> Conversation | None:
    """Get a conversation by ID."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow("SELECT * FROM conversation WHERE id = $1", conversation_id)
        return Conversation(**dict(row)) if row else None


async def get_customer_conversations(
    customer_id: UUID, limit: int = 50, offset: int = 0
) -> list[Conversation]:
    """Get all conversations for a customer."""
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM conversation
            WHERE customer_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            customer_id,
            limit,
            offset,
        )
        return [Conversation(**dict(row)) for row in rows]


async def get_business_conversations(
    business_id: UUID,
    status: ConversationStatus | str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Conversation]:
    """Get all conversations for a business, optionally filtered by status."""
    async with get_db_connection() as conn:
        if status:
            status_value = status if isinstance(status, str) else status.value
            rows = await conn.fetch(
                """
                SELECT * FROM conversation
                WHERE business_id = $1 AND status = $2
                ORDER BY created_at DESC
                LIMIT $3 OFFSET $4
                """,
                business_id,
                status_value,
                limit,
                offset,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM conversation
                WHERE business_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                business_id,
                limit,
                offset,
            )
        return [Conversation(**dict(row)) for row in rows]


async def update_conversation(conversation_id: UUID, **updates) -> Conversation | None:
    """Update a conversation with arbitrary fields."""
    if not updates:
        return await get_conversation_by_id(conversation_id)

    # Build dynamic UPDATE query
    set_clauses = ", ".join([f"{key} = ${i + 2}" for i, key in enumerate(updates.keys())])
    values = [conversation_id] + list(updates.values())

    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE conversation
            SET {set_clauses}, updated_at = NOW()
            WHERE id = $1
            RETURNING *
            """,
            *values,
        )
        return Conversation(**dict(row)) if row else None


async def escalate_conversation(
    conversation_id: UUID, assigned_to_user_id: UUID
) -> Conversation | None:
    """Escalate a conversation to a user (sets status, user_id, and timestamp)."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            """
            UPDATE conversation
            SET status = 'escalated',
                assigned_to_user_id = $2,
                escalated_at = $3,
                updated_at = NOW()
            WHERE id = $1
            RETURNING *
            """,
            conversation_id,
            assigned_to_user_id,
            datetime.now(),
        )
        return Conversation(**dict(row)) if row else None


async def delete_conversation(conversation_id: UUID) -> bool:
    """Delete a conversation."""
    async with get_db_connection() as conn:
        result = await conn.execute("DELETE FROM conversation WHERE id = $1", conversation_id)
        return result == "DELETE 1"
