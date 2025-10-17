"""Agent query functions."""

from uuid import UUID

from db.connection import get_db_connection
from db.models.agent import Agent


async def create_agent(
    business_id: UUID,
    name: str,
    key: str,
    system_prompt: str,
    tool_groups: list[str] | None = None,
    subagents: list[str] | None = None,
    metadata: dict | None = None,
    channels: dict | None = None,
    status: str = "active",
) -> Agent:
    """Create a new agent for a business.

    Args:
        business_id: ID of the business
        name: Display name (e.g., "Legal Assistant Sarah")
        key: System identifier/routing key (e.g., "legal", "support")
        system_prompt: Agent's behavioral instructions
        tool_groups: List of toolset names (e.g., ["catalog", "customers"])
        subagents: List of agent keys this agent can transfer to
        metadata: Optional fields (personality, tone, greeting_message, avatar_url, etc.)
        channels: Channel configuration
        status: Agent status (default: "active")
    """
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO agent (
                business_id, name, key, system_prompt, tool_groups, subagents,
                metadata, channels, status
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
            """,
            business_id,
            name,
            key,
            system_prompt,
            tool_groups or ["catalog", "customers", "conversations"],
            subagents or [],
            metadata or {},
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
    """Get the first active agent for a business.

    Note: This returns the first active agent. For multi-agent scenarios,
    use get_agent_by_key() instead.
    """
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM agent
            WHERE business_id = $1 AND status = 'active'
            ORDER BY created_at
            LIMIT 1
            """,
            business_id,
        )
        return Agent(**dict(row)) if row else None


async def get_agent_by_key(business_id: UUID, key: str) -> Agent | None:
    """Get an agent by business ID and key."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM agent
            WHERE business_id = $1 AND key = $2 AND status = 'active'
            """,
            business_id,
            key,
        )
        return Agent(**dict(row)) if row else None


async def get_business_agents(business_id: UUID, active_only: bool = True) -> list[Agent]:
    """Get all agents for a business."""
    async with get_db_connection() as conn:
        if active_only:
            rows = await conn.fetch(
                """
                SELECT * FROM agent
                WHERE business_id = $1 AND status = 'active'
                ORDER BY created_at
                """,
                business_id,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM agent
                WHERE business_id = $1
                ORDER BY created_at
                """,
                business_id,
            )
        return [Agent(**dict(row)) for row in rows]


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
