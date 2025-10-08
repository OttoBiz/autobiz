"""Agent execution activity using Pydantic AI's TemporalAgent.

State Management:
- Loads conversation state from PostgreSQL via StateManager
- State is passed to agent via dependencies
- Saves updated state back to PostgreSQL after execution
"""

from datetime import datetime, timezone
from uuid import UUID

from pydantic_ai.durable_exec.temporal import TemporalAgent
from temporalio import activity

from agents.deps import AgentDeps
from agents.executor import AgentExecutor
from agents.state.manager import StateManager
from db.connection import get_db_pool
from temporal.models import AgentResponse, ConversationState


@activity.defn
async def execute_agent(
    conversation_id: str,
    business_id: str,
    agent_id: str,
    message: str,
) -> AgentResponse:
    """Execute agent to process customer message.

    This activity:
    1. Loads conversation state from PostgreSQL
    2. Executes agent with state in dependencies
    3. Saves updated state back to PostgreSQL

    Args:
        conversation_id: UUID of the conversation
        business_id: UUID of the business
        agent_id: UUID of the agent
        message: Customer message to process

    Returns:
        AgentResponse with message and optional transfer/pause instructions
    """
    activity.logger.info(f"Executing agent {agent_id} for conversation {conversation_id}")

    # Convert string UUIDs to UUID objects
    conv_id = UUID(conversation_id)
    biz_id = UUID(business_id)
    agt_id = UUID(agent_id)

    # Get database connection
    pool = await get_db_pool()

    # Load conversation state from PostgreSQL
    state_manager = StateManager()
    state_manager.db_pool = pool

    state = await state_manager.get_state(conv_id)

    # Create new state if none exists
    if not state:
        state = ConversationState(
            conversation_id=conv_id,
            business_id=biz_id,
            current_agent_id=agt_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    # Create agent dependencies
    deps = AgentDeps(
        business_id=biz_id,
        conversation_id=conv_id,
    )

    # Initialize executor with state manager
    executor = AgentExecutor(state_manager=state_manager)

    # Load agent config from database by agent_id
    async with pool.acquire() as conn:
        agent_row = await conn.fetchrow(
            """
            SELECT id, role, config
            FROM agent
            WHERE id = $1 AND business_id = $2
            """,
            agt_id,
            biz_id,
        )

        if not agent_row:
            raise ValueError(f"Agent {agent_id} not found for business {business_id}")

        agent_role = agent_row["role"]

    # Load agent config by role
    config = await executor.load_agent_config(biz_id, agent_role)

    if not config:
        raise ValueError(f"Agent config not found for role {agent_role}")

    # Create Pydantic AI agent
    agent = executor.create_agent(config)

    # Wrap agent with TemporalAgent for automatic activity wrapping
    # This ensures all agent tool calls are executed as Temporal activities
    temporal_agent = TemporalAgent(agent)

    # Run agent with message history for context (Pydantic AI pattern)
    result = await temporal_agent.run(
        message,
        message_history=state.messages,  # Pass conversation history for context
        deps=deps,
    )

    # Update state with new messages from this run
    state.messages.extend(result.new_messages())
    state.updated_at = datetime.now(timezone.utc)
    state.last_activity_at = datetime.now(timezone.utc)

    # Update token usage
    if result.usage():
        state.total_tokens_used += result.usage().total_tokens

    # Save state back to PostgreSQL
    await state_manager.save_state(state)

    # Parse result for transfer/pause instructions
    response_text = result.output if isinstance(result.output, str) else str(result.output)

    # Check if agent used collaboration tools (these update state directly)
    should_transfer = False
    transfer_to_agent_id = None
    transfer_to_role = None
    should_pause = False
    pause_reason = None

    # Parse tool calls for collaboration actions
    for msg in result.new_messages():
        if hasattr(msg, "parts"):
            for part in msg.parts:
                # Check for handoff tool calls
                if hasattr(part, "tool_name") and "handoff" in part.tool_name.lower():
                    should_transfer = True
                    # Tool should have updated state already
                    # Get updated state to find new agent
                    updated_state = await state_manager.get_state(conv_id)
                    if updated_state:
                        transfer_to_agent_id = updated_state.current_agent_id
                        # TODO: Look up agent role from agent_id
                        transfer_to_role = "unknown"

                # Check for pause-related tools
                if hasattr(part, "tool_name") and any(
                    keyword in part.tool_name.lower() for keyword in ["pause", "escalate", "human"]
                ):
                    should_pause = True
                    updated_state = await state_manager.get_state(conv_id)
                    if updated_state:
                        pause_reason = updated_state.pause_reason

    return AgentResponse(
        message=response_text,
        should_transfer=should_transfer,
        transfer_to_agent_id=transfer_to_agent_id,
        transfer_to_role=transfer_to_role,
        should_pause=should_pause,
        pause_reason=pause_reason,
    )
