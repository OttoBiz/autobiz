"""Multi-agent executor for running business agents with toolsets.

This module handles:
- Loading agent configurations from the database
- Composing toolsets based on agent definition
- Executing agent workflows with proper state management
- Handling agent collaboration (handoff and consult)

Agent outputs are structured using the union type AgentOutput:
- MessageResponse: Standard response to customer
- HandoffResponse: Transfer control to another agent (recursive execution)
- PauseResponse: Pause conversation until external event
- MultiMessageResponse: Send multiple messages sequentially

See docs/architecture/STRUCTURED_OUTPUT.md for detailed pattern explanation.
"""

import asyncio
import yaml
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import Agent

from agents.deps import AgentDeps
from agents.models import (
    AgentOutput,
    HandoffResponse,
    MessageResponse,
    MultiMessageResponse,
    PauseResponse,
)
from agents.registry import ToolsetManager, get_toolset_manager


class AgentConfig(BaseModel):
    """Configuration for an AI agent loaded from database.

    Maps to the 'agent' table JSONB config column.
    Follows Claude Code subagent YAML pattern stored in JSONB.
    """

    id: UUID | None = None
    business_id: UUID | None = None
    name: str
    key: str  # e.g., "sales", "legal_intake", "customer_support"
    system_prompt: str

    # Tool groups this agent has access to
    tool_groups: list[str]  # List of toolset names (e.g., ["catalog", "customers", "collab"])

    # Collaboration settings
    subagents: list[str] = []  # List of agent keys this agent can hand off to

    # Optional configurations
    channels: dict[str, Any] = {}
    metadata: dict[str, Any] = {}

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
        model: str = "openai:gpt-4o",
    ):
        """Initialize the agent executor.

        Args:
            toolset_manager: Manager for composing toolsets (uses global if None)
            model: AI model to use (default: GPT-4o)
        """
        self.toolset_manager = toolset_manager or get_toolset_manager()
        self.model = model
        self._cached_configs: dict[str, AgentConfig] = {}

    async def load_agent_config(
        self, business_id: UUID | None, agent_key: str
    ) -> AgentConfig | None:
        """Load agent configuration from database.

        Args:
            business_id: ID of the business
            agent_key: Key of the agent (e.g., "sales", "legal_intake")

        Returns:
            Agent configuration or None if not found
        """
        if agent_key in self._cached_configs:
            return self._cached_configs[agent_key]
        # TODO: Try database if business_id provided
        # if business_id:
        #     config = await get_agent_by_key(business_id, agent_key)
        #     if config:
        #         return config
        return None

    async def load_agents_from_yaml(self, path: str | Path) -> list[AgentConfig]:
        """Load agent configuration from YAML file."""
        try:
            with open(path, "r") as f:
                agent_configs = yaml.safe_load(f)

                agents_data = agent_configs.get("agents", [])

                agent_keys = {agent["key"] for agent in agents_data}

                configs = []

                for agent_dict in agents_data:
                    subagents = agent_dict.get("subagents", [])
                    for subagent_key in subagents:
                        if subagent_key not in agent_keys:
                            raise ValueError(
                                f"Agent {agent_dict['key']} references unknown subagent '{subagent_key}'"
                            )
                    agent_config = AgentConfig(**agent_dict)
                    configs.append(agent_config)

                    # Cache the config by key
                    self._cached_configs[agent_config.key] = agent_config

                return configs

        except FileNotFoundError:
            raise FileNotFoundError(f"Agent config file not found: {path}")

    def create_agent(self, config: AgentConfig) -> Agent[AgentDeps, AgentOutput]:
        """Create a Pydantic AI agent from configuration.

        Composes toolsets based on the agent's tool_groups.

        Args:
            config: Agent configuration

        Returns:
            Configured Pydantic AI agent
        """
        # Combine toolsets based on agent configuration
        toolset = self.toolset_manager.combine(config.tool_groups)

        # Build system prompt - only add collaboration guidance if agent has collab tools
        has_collab = "collab" in config.tool_groups

        if has_collab:
            system_prompt = f"""{config.system_prompt}

## Collaboration Guidelines

**CONSULT** another agent (use `consult` tool):
- Simple GET: You need specific information
- Tool returns answer to you, you continue conversation

**HANDOFF** to another agent (return HandoffResponse):
- WRITE operation or Complex GET
- Customer needs specialist
- Return structured response (NOT a tool call)

To handoff, return this exact structure:
{{{{
    "type": "handoff",
    "target_agent_key": "legal",
    "reason": "Customer needs contract review",
    "context_summary": "Brief context",
    "priority": "medium"
}}}}

**Golden Rule**: Will the OTHER agent need to talk to the customer?
- YES → Return HandoffResponse
- NO → Use consult tool
"""
        else:
            system_prompt = config.system_prompt

        # Create agent with toolset
        agent = Agent(
            self.model,
            deps_type=AgentDeps,
            system_prompt=system_prompt,
            toolsets=toolset,
            output_type=AgentOutput,
        )

        return agent

    async def run(
        self,
        agent_key: str,
        user_message: str,
        deps: AgentDeps,
        business_id: UUID | None = None,
        conversation_id: UUID | None = None,
        message_history: list | None = None,
    ) -> str:
        """Execute an agent to handle a user message.

        Supports structured output pattern with pattern matching on output types:
        - MessageResponse: Send to customer via channel
        - HandoffResponse: Transfer to another agent (recursive)
        - PauseResponse: Pause conversation until external event
        - MultiMessageResponse: Send multiple messages sequentially

        Args:
            business_id: ID of the business
            conversation_id: ID of the conversation
            agent_key: Key of the agent to run
            user_message: Message from the user
            deps: Agent dependencies
            message_history: Previous messages to maintain conversation context

        Returns:
            Agent's response content (what was sent to customer)
        """
        # Load agent configuration
        config = await self.load_agent_config(business_id, agent_key)
        if not config:
            raise ValueError(f"Agent '{agent_key}' not found")

        # Update deps with current agent info
        deps = replace(
            deps,
            current_agent_id=config.id,
            current_agent_key=agent_key,
        )

        # Create agent with tools
        agent = self.create_agent(config)

        # Run agent with structured output
        # Pass message_history to maintain conversation context across handoffs
        result = await agent.run(
            user_message,
            deps=deps,
            message_history=message_history or [],
        )

        # Pattern match on output type
        match result.output:
            case MessageResponse(content=content, metadata=metadata):
                # Standard response - send to channel
                await self._send_to_channel(deps.channel, content, metadata)
                return content

            case HandoffResponse(
                target_agent_key=target_key,
                reason=reason,
                context_summary=summary,
                priority=priority,
            ):
                # Handoff requested - record and continue with new agent
                await self._record_handoff(
                    conversation_id=conversation_id,
                    from_agent_id=config.id,
                    from_agent_key=agent_key,
                    to_agent_key=target_key,
                    reason=reason,
                )

                # Update context variables with handoff info
                new_context = {
                    **deps.context_variables,
                    "handoff_reason": reason,
                    "handoff_from": agent_key,
                    "handoff_priority": priority,
                }

                new_deps = replace(deps, context_variables=new_context)

                # Build handoff message for the new agent
                # The new agent starts a fresh conversation but has context
                handoff_message = f"""[HANDOFF CONTEXT]
You are receiving this customer via handoff from the {agent_key} agent.

Reason for handoff: {reason}
Priority: {priority}
Context summary: {summary}

Please introduce yourself and help the customer with their request.
"""

                # Start a fresh conversation (no message_history)
                # The context summary provides what the new agent needs to know
                return await self.run(
                    business_id=business_id,
                    conversation_id=conversation_id,
                    agent_key=target_key,
                    user_message=handoff_message,
                    deps=new_deps,
                    message_history=message_history,  # Fresh conversation for new agent
                )

            case PauseResponse(content=content):
                # Pause conversation - send message
                # TODO: Implement state persistence for pause/resume
                await self._send_to_channel(deps.channel, content)
                return content

            case MultiMessageResponse(messages=messages, delay_between_ms=delay):
                # Multiple messages - send sequentially with delay
                for i, msg in enumerate(messages):
                    await self._send_to_channel(
                        deps.channel,
                        msg.content,
                        media_url=msg.media_url,
                        media_type=msg.media_type,
                    )
                    if i < len(messages) - 1:  # Don't delay after last message
                        await asyncio.sleep(delay / 1000)

                # Return combined content for logging
                return "\n".join(msg.content for msg in messages)

    # Helper methods for structured output pattern

    async def _send_to_channel(
        self,
        channel: str | None,
        content: str,
        metadata: dict[str, Any] | None = None,
        media_url: str | None = None,
        media_type: str | None = None,
    ) -> None:
        """Send message to appropriate channel (WhatsApp, SMS, email, etc.).

        Args:
            channel: Channel identifier (e.g., "whatsapp", "sms", "email")
            content: Message content to send
            metadata: Optional metadata for the message
            media_url: Optional media URL to attach
            media_type: Type of media (image, video, document)
        """
        # TODO: Implement channel-specific message sending
        # For now, just log the message
        # In production, this would:
        # 1. Load channel integration (WhatsApp, SMS, etc.)
        # 2. Format message for channel (some channels support rich formatting)
        # 3. Send via channel API
        # 4. Track delivery status
        pass

    async def _record_handoff(
        self,
        business_id: UUID | None = None,
        conversation_id: UUID | None = None,
        from_agent_id: UUID | None = None,
        from_agent_key: str | None = None,
        to_agent_id: UUID | None = None,
        to_agent_key: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Record handoff in database for audit/analytics.

        This is NOT used for runtime logic - just for tracking and analytics.

        Args:
            business_id: ID of the business
            conversation_id: ID of the conversation
            from_agent_id: ID of agent initiating handoff
            from_agent_key: Key of agent initiating handoff
            to_agent_id: ID of agent receiving handoff
            to_agent_key: Key of agent receiving handoff
            reason: Why the handoff is happening
        """
        # TODO: Implement database recording
        # Simple INSERT - no complex logic needed
        # Example:
        # await self.db.execute(
        #     """
        #     INSERT INTO agent_collaborations (
        #         conversation_id, from_agent_id, to_agent_id,
        #         collaboration_type, reason, created_at
        #     ) VALUES ($1, $2, $3, 'handoff', $4, NOW())
        #     """,
        #     conversation_id, from_agent_id, to_agent_id, reason
        # )
        pass
