"""Simple toolset manager for composing agent toolsets.

No business logic - just composing and retrieving toolsets.
"""

from pydantic_ai import AbstractToolset, FunctionToolset

from agents.toolsets import (
    ALL_TOOLS,
    catalog_toolset,
    collaboration_toolset,
    conversations_toolset,
    customers_toolset,
)


class ToolsetManager:
    """Manages toolsets with simple composition.

    This manager provides access to domain-organized toolsets and allows
    combining them to create agent-specific tool collections.

    No filtering or business logic - that happens elsewhere. This class
    is purely about toolset composition.

    Example:
        manager = ToolsetManager()

        # Get individual toolset
        catalog = manager.get("catalog")

        # Combine multiple toolsets
        sales_tools = manager.combine(["catalog", "customers", "collab"])

        # Get all tools
        all_tools = manager.all_tools
    """

    def __init__(self):
        """Initialize toolset manager with all available toolsets."""
        # Individual domain toolsets
        self.catalog = catalog_toolset
        self.customers = customers_toolset
        self.conversations = conversations_toolset
        self.collab = collaboration_toolset

        # Master toolset (list of all toolsets - compose with Agent(..., tools=[...]))
        self.all_tools = ALL_TOOLS

    def get(self, name: str) -> AbstractToolset:
        """Get a domain toolset by name.

        Args:
            name: Toolset name ("catalog", "customers", "conversations", "collab")

        Returns:
            The requested toolset, or empty toolset if not found
        """
        return getattr(self, name, FunctionToolset())

    def combine(self, tool_groups: list[str]) -> list[AbstractToolset]:
        """Combine multiple domain toolsets into a list.

        Args:
            tool_groups: List of toolset names to combine
                        (e.g., ["catalog", "customers", "collab"])

        Returns:
            List of toolsets to pass to Agent(tools=[...])

        Example:
            # Sales agent gets catalog, customers, and collaboration tools
            toolsets = manager.combine(["catalog", "customers", "collab"])
            agent = Agent(model, tools=toolsets, ...)

            # Support agent gets all conversation tools
            toolsets = manager.combine(["conversations", "customers"])
        """
        return [self.get(group) for group in tool_groups]


# Global instance for convenience
_manager = ToolsetManager()


def get_toolset_manager() -> ToolsetManager:
    """Get the global toolset manager instance.

    Returns:
        Global ToolsetManager instance
    """
    return _manager
