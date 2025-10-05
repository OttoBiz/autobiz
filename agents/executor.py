"""Multi-agent executor for running business agents with toolsets.

This module handles:
- Loading agent configurations from the database
- Composing toolsets based on agent definition
- Executing agent workflows with proper state management
- Handling agent collaboration (handoff and consult)
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import Agent

from agents.deps import AgentDeps
from agents.registry import ToolsetManager, get_toolset_manager
from agents.state.manager import ConversationState, StateManager


class AgentConfig(BaseModel):
    """Configuration for an AI agent loaded from database.

    Maps to the 'agent' table JSONB config column.
    Follows Claude Code subagent YAML pattern stored in JSONB.
    """

    id: UUID
    business_id: UUID
    name: str
    role: str  # e.g., "sales", "legal_intake", "customer_support"
    system_prompt: str
    personality: str | None = None
    tone: str | None = None

    # Tool groups this agent has access to
    tool_groups: list[str]  # List of toolset names (e.g., ["catalog", "customers", "collab"])

    # Collaboration settings
    can_handoff_to: list[str] = []  # List of agent roles this agent can hand off to
    can_consult: list[str] = []  # List of agent roles this agent can consult

    # Optional configurations
    greeting_message: str | None = None
    conversation_rules: dict[str, Any] = {}
    channels: dict[str, Any] = {}

    # Metadata
    status: str = "active"
    version: int = 1


class AgentExecutor:
    """Executes AI agents with toolset composition and state management.

    This is the core orchestrator for the multi-agent system.
    """

    def __init__(
        self,
        toolset_manager: ToolsetManager | None = None,
        state_manager: StateManager | None = None,
        model: str = "openai:gpt-4o",
    ):
        """Initialize the agent executor.

        Args:
            toolset_manager: Manager for composing toolsets (uses global if None)
            state_manager: Manager for conversation state
            model: AI model to use (default: GPT-4o)
        """
        self.toolset_manager = toolset_manager or get_toolset_manager()
        self.state_manager = state_manager
        self.model = model

    async def load_agent_config(
        self, business_id: UUID, agent_role: str
    ) -> AgentConfig | None:
        """Load agent configuration from database.

        Args:
            business_id: ID of the business
            agent_role: Role of the agent (e.g., "sales", "legal_intake")

        Returns:
            Agent configuration or None if not found
        """
        # TODO: Implement database query
        # SELECT * FROM agent WHERE business_id = $1 AND role = $2
        raise NotImplementedError("Agent config loading not yet implemented")

    def create_agent(self, config: AgentConfig) -> Agent:
        """Create a Pydantic AI agent from configuration.

        Composes toolsets based on the agent's tool_groups.

        Args:
            config: Agent configuration

        Returns:
            Configured Pydantic AI agent
        """
        # Combine toolsets based on agent configuration
        toolset = self.toolset_manager.combine(config.tool_groups)

        # Build system prompt with collaboration guidance
        system_prompt = f"""{config.system_prompt}

## Collaboration Guidelines

When working with other agents:

**CONSULT** another agent when:
- Simple GET: You need specific information (inventory count, policy, approval)
- One question → one answer
- You continue handling conversation after getting the answer
- Customer doesn't see the consultation

Example: "What's inventory count for SKU-123?" → Simple data lookup

**HANDOFF** to another agent when:
- WRITE operation: Create order, process refund, update data
- Complex GET: Customer needs multi-turn interaction with specialist
- Customer explicitly requests different service
- You lack the tools or authority to continue

Example (WRITE): "Process this refund" → Changes order state
Example (Complex GET): "Design enterprise solution" → Multi-turn with specialist

**Golden Rule**: Will the OTHER agent need to talk to the customer?
- YES → Use collab_handoff
- NO → Use collab_consult

Remember: CONSULT = Simple GET, HANDOFF = WRITE + Complex GET
"""

        # Create agent with toolset
        agent = Agent(
            self.model,
            deps_type=AgentDeps,
            system_prompt=system_prompt,
            tools=toolset,
        )

        return agent

    async def run(
        self,
        business_id: UUID,
        conversation_id: UUID,
        agent_role: str,
        user_message: str,
        deps: AgentDeps,
    ) -> str:
        """Execute an agent to handle a user message.

        Args:
            business_id: ID of the business
            conversation_id: ID of the conversation
            agent_role: Role of the agent to run
            user_message: Message from the user
            deps: Agent dependencies

        Returns:
            Agent's response
        """
        # Load agent configuration
        config = await self.load_agent_config(business_id, agent_role)
        if not config:
            raise ValueError(f"Agent '{agent_role}' not found for business {business_id}")

        # Create agent with tools
        agent = self.create_agent(config)

        # Update conversation state (if state manager is available)
        if self.state_manager:
            await self.state_manager.save_state(
                ConversationState(
                    conversation_id=conversation_id,
                    business_id=business_id,
                    current_agent_id=config.id,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
            )

        # Run agent
        result = await agent.run(user_message, deps=deps)

        return result.data

    async def handoff(
        self,
        conversation_id: UUID,
        from_agent_role: str,
        to_agent_role: str,
        reason: str,
        context: str,
        deps: AgentDeps,
    ) -> str:
        """Execute an agent handoff.

        Transfers conversation control from one agent to another.
        Used for WRITE operations or complex GET operations that require
        specialized expertise.

        Args:
            conversation_id: ID of the conversation
            from_agent_role: Role of agent initiating handoff
            to_agent_role: Role of agent receiving handoff
            reason: Why the handoff is happening
            context: Context to pass to the new agent
            deps: Agent dependencies

        Returns:
            Response from the receiving agent
        """
        # TODO: Implement handoff logic
        # 1. Verify handoff is allowed (from_agent can handoff to to_agent)
        # 2. Load receiving agent config
        # 3. Record handoff in state
        # 4. Execute receiving agent with context
        raise NotImplementedError("Agent handoff not yet implemented")

    async def consult(
        self,
        conversation_id: UUID,
        requesting_agent_role: str,
        consulted_agent_role: str,
        query: str,
        deps: AgentDeps,
    ) -> str:
        """Execute an agent consultation.

        Temporarily consults another agent for information, then returns control
        to the requesting agent. Used for simple GET operations.

        Args:
            conversation_id: ID of the conversation
            requesting_agent_role: Role of agent requesting consultation
            consulted_agent_role: Role of agent being consulted
            query: Question to ask the consulted agent
            deps: Agent dependencies

        Returns:
            Response from the consulted agent
        """
        # TODO: Implement consult logic
        # 1. Verify consult is allowed
        # 2. Load consulted agent config
        # 3. Record consult in state
        # 4. Execute consulted agent with query
        # 5. Return response (control stays with requesting agent)
        raise NotImplementedError("Agent consultation not yet implemented")


