"""Toolsets for AI agents.

This module exports domain-organized toolsets that can be composed together
to create agents with specific capabilities.

All toolsets use prefixes to prevent naming collisions:
- catalog_* - Product catalog and inventory tools
- customers_* - Customer management tools
- conversations_* - Conversation and messaging tools
- collab_* - Agent collaboration tools (handoff, consult)

Example usage:
    # Combine toolsets for a sales agent
    from agents.toolsets import ToolsetManager

    manager = ToolsetManager()
    sales_toolset = manager.combine(["catalog", "customers", "collab"])

    # Create agent with toolset
    agent = Agent(
        model="openai:gpt-4o",
        tools=sales_toolset,
        system_prompt="You are a sales agent..."
    )
"""

from agents.toolsets.catalog import catalog_toolset
from agents.toolsets.collaboration import collaboration_toolset
from agents.toolsets.conversations import conversations_toolset
from agents.toolsets.customers import customers_toolset

# Master toolset combining all available tools
# This represents the complete tool inventory (stable for KV-cache optimization)
# Note: We combine toolsets in ToolsetManager.combine() instead of at module level
# to avoid issues with FunctionToolset composition
ALL_TOOLS = [
    catalog_toolset,
    customers_toolset,
    conversations_toolset,
    collaboration_toolset,
]

__all__ = [
    "catalog_toolset",
    "customers_toolset",
    "conversations_toolset",
    "collaboration_toolset",
    "ALL_TOOLS",
]
