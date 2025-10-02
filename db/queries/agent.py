"""Agent query functions."""

from uuid import UUID

import asyncpg

from db.connection import get_db_connection
from db.models.agent import Agent


async def create_agent(
    business_id: UUID,
    name: str,
    system_prompt: str,
    avatar_url: str | None = None,
    personality: str | None = None,
    tone: str | None = None,
    greeting_message: str | None = None,
    conversation_rules: dict | None = None,
    channels: dict | None = None,
    status: str = "active",
) -> Agent:
    """Create a new agent for a business."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO agent (
                business_id, name, system_prompt, avatar_url, personality, tone,
                greeting_message, conversation_rules, channels, status
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
            """,
            business_id,
            name,
            system_prompt,
            avatar_url,
            personality,
            tone,
            greeting_message,
            conversation_rules or {},
            channels
            or {
                "whatsapp": {"enabled": False, "credentials": {}, "config": {}},
                "webchat": {"enabled": False, "config": {}},
                "sms": {"enabled": False, "credentials": {}, "config": {}},
                "email": {"enabled": False, "credentials": {}, "config": {}},
            },
            status,
        )
        return Agent(**dict(row))


async def get_agent_by_id(agent_id: UUID) -> Agent | None:
    """Get an agent by ID."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow("SELECT * FROM agent WHERE id = $1", agent_id)
        return Agent(**dict(row)) if row else None


async def get_agent_by_business_id(business_id: UUID) -> Agent | None:
    """Get an agent by business ID (one agent per business)."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow("SELECT * FROM agent WHERE business_id = $1", business_id)
        return Agent(**dict(row)) if row else None


async def update_agent(agent_id: UUID, **updates) -> Agent | None:
    """Update an agent with arbitrary fields."""
    if not updates:
        return await get_agent_by_id(agent_id)

    # Build dynamic UPDATE query
    set_clauses = ", ".join([f"{key} = ${i + 2}" for i, key in enumerate(updates.keys())])
    values = [agent_id] + list(updates.values())

    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE agent
            SET {set_clauses}, updated_at = NOW()
            WHERE id = $1
            RETURNING *
            """,
            *values,
        )
        return Agent(**dict(row)) if row else None


async def delete_agent(agent_id: UUID) -> bool:
    """Delete an agent."""
    async with get_db_connection() as conn:
        result = await conn.execute("DELETE FROM agent WHERE id = $1", agent_id)
        return result == "DELETE 1"
