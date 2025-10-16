"""Webhook endpoints for receiving customer messages from channels."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.deps import AgentDeps
from agents.executor import AgentConfig, AgentExecutor
from db.connection import get_db_pool
from db.queries.agent import get_agent_by_business_id
from db.queries.conversation import create_conversation, get_conversation_by_id
from db.queries.message import create_message, get_conversation_messages

router = APIRouter()


class IncomingMessage(BaseModel):
    """Incoming message from a channel webhook."""

    business_id: UUID
    customer_id: UUID | None = None
    conversation_id: UUID | None = None
    channel: str  # "whatsapp", "sms", etc.
    message: str
    metadata: dict = {}


class ProductionAgentExecutor(AgentExecutor):
    """Production executor that loads agent configs from database."""

    async def load_agent_config(self, business_id: UUID, agent_key: str) -> AgentConfig | None:
        """Load agent configuration from database.

        Args:
            business_id: ID of the business
            agent_key: Agent's routing key (e.g., "sales", "legal")

        Returns:
            Agent configuration or None if not found
        """
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, business_id, name, key, system_prompt, tool_groups,
                       can_handoff_to, metadata, channels, status
                FROM agent
                WHERE business_id = $1 AND key = $2 AND status = 'active'
                """,
                business_id,
                agent_key,
            )

            if not row:
                return None

            # Extract optional fields from metadata
            metadata = row["metadata"] or {}

            # Map database row to AgentConfig
            return AgentConfig(
                id=row["id"],
                business_id=row["business_id"],
                name=row["name"],
                role=row["key"],  # Map key to role for AgentConfig
                system_prompt=row["system_prompt"],
                tool_groups=row["tool_groups"] or ["catalog", "customers", "conversations"],
                can_handoff_to=row["can_handoff_to"] or [],
                can_consult=[],  # Derived from tool_groups (if "collab" in tools, can consult)
                personality=metadata.get("personality"),
                tone=metadata.get("tone"),
                greeting_message=metadata.get("greeting_message"),
                conversation_rules=metadata.get("conversation_rules", {}),
                channels=row["channels"] or {},
                status=row["status"],
            )

    async def _send_to_channel(
        self,
        channel: str,
        content: str,
        metadata: dict | None = None,
        media_url: str | None = None,
        media_type: str | None = None,
    ) -> None:
        """Send message to customer via channel.

        This would integrate with channel providers (WhatsApp, SMS, etc.).
        For now, it's a placeholder that could be implemented later.
        """
        # TODO: Implement actual channel integration
        # For now, messages are stored in database only
        pass

    async def _record_handoff(
        self,
        conversation_id: UUID,
        from_agent_id: UUID,
        from_agent_role: str,
        to_agent_role: str,
        reason: str,
    ) -> None:
        """Record agent handoff in database.

        This creates an internal message marking the handoff.
        """
        await create_message(
            conversation_id=conversation_id,
            sender_type="system",
            content=f"Handoff: {from_agent_role} → {to_agent_role}. Reason: {reason}",
            is_internal=True,
        )


@router.post("/message")
async def receive_message(payload: IncomingMessage):
    """Receive customer message from channel webhook.

    This endpoint:
    1. Creates or retrieves conversation
    2. Saves incoming message to database
    3. Executes agent to generate response
    4. Saves agent response to database
    5. Returns response (actual channel delivery happens async)
    """
    pool = await get_db_pool()

    # Get or create conversation
    if payload.conversation_id:
        conversation = await get_conversation_by_id(payload.conversation_id)
        if not conversation or conversation.business_id != payload.business_id:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        # Create new conversation
        conversation = await create_conversation(
            business_id=payload.business_id,
            customer_id=payload.customer_id,
            channel=payload.channel,
            metadata=payload.metadata,
        )

    # Save customer message
    await create_message(
        conversation_id=conversation.id,
        sender_type="customer",
        content=payload.message,
    )

    # Get default agent for business
    agent = await get_agent_by_business_id(payload.business_id)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"No active agent found for business {payload.business_id}",
        )

    # Get conversation history for context
    messages = await get_conversation_messages(
        conversation.id, include_internal=False, limit=50
    )

    # Convert to message history format for agent
    # Pydantic AI expects list of message dicts
    message_history = [
        {"role": "user" if msg.sender_type == "customer" else "assistant", "content": msg.content}
        for msg in messages[:-1]  # Exclude the message we just saved
    ]

    # Create executor and run agent
    executor = ProductionAgentExecutor()

    # Create agent dependencies
    deps = AgentDeps(
        business_id=payload.business_id,
        conversation_id=conversation.id,
        customer_id=payload.customer_id,
        channel=payload.channel,
    )

    try:
        # Execute agent
        response_content = await executor.run(
            business_id=payload.business_id,
            conversation_id=conversation.id,
            agent_role=agent.key,  # Use agent's routing key
            user_message=payload.message,
            deps=deps,
            message_history=message_history,
        )

        # Save agent response
        await create_message(
            conversation_id=conversation.id,
            sender_type="agent",
            content=response_content,
        )

        return {
            "status": "success",
            "conversation_id": str(conversation.id),
            "response": response_content,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error executing agent: {str(e)}",
        )
