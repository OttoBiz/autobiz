"""Example demonstrating toolset composition with ToolsetManager.

This shows how to create specialized agents with different tool combinations.

Run with:
    uv run python -m examples.toolset_composition
"""

from uuid import uuid4

from pydantic_ai import Agent

from agents.deps import AgentDeps
from agents.registry import ToolsetManager


def create_sales_agent(toolset_manager: ToolsetManager) -> Agent:
    """Create a sales-focused agent with catalog and customer tools."""
    return Agent(
        "openai:gpt-4o-mini",
        deps_type=AgentDeps,
        system_prompt="""You are a sales agent. Your goal is to help customers find products
and make purchases. Be enthusiastic and helpful!""",
        tools=toolset_manager.combine(["catalog", "customers"]),
    )


def create_support_agent(toolset_manager: ToolsetManager) -> Agent:
    """Create a support agent with conversation and customer tools."""
    return Agent(
        "openai:gpt-4o-mini",
        deps_type=AgentDeps,
        system_prompt="""You are a customer support agent. Help resolve issues,
answer questions, and escalate when needed. Be patient and understanding.""",
        tools=toolset_manager.combine(["customers", "conversations"]),
    )


def create_orchestrator_agent(toolset_manager: ToolsetManager) -> Agent:
    """Create an orchestrator agent that can collaborate with other agents."""
    return Agent(
        "openai:gpt-4o-mini",
        deps_type=AgentDeps,
        system_prompt="""You are an orchestrator agent. You can consult other agents
or hand off conversations when needed. Decide when to handle things yourself
vs when to involve specialists.""",
        tools=toolset_manager.combine(["catalog", "customers", "conversations", "collab"]),
    )


def main():
    """Demonstrate different agent configurations."""
    manager = ToolsetManager()

    print("🎯 Toolset Composition Examples")
    print("=" * 60)
    print()

    # Example 1: Sales Agent Tools
    print("1️⃣  Sales Agent Toolsets")
    print("-" * 60)
    sales_toolsets = manager.combine(["catalog", "customers"])
    print(f"   Toolsets: {[type(t).__name__ for t in sales_toolsets]}")
    print(f"   Usage: Agent(model, tools=manager.combine(['catalog', 'customers']))")
    print(f"   Tools: catalog_product_search, catalog_inventory_check, customers_lookup")
    print()

    # Example 2: Support Agent Tools
    print("2️⃣  Support Agent Toolsets")
    print("-" * 60)
    support_toolsets = manager.combine(["customers", "conversations"])
    print(f"   Toolsets: {[type(t).__name__ for t in support_toolsets]}")
    print(f"   Usage: Agent(model, tools=manager.combine(['customers', 'conversations']))")
    print(f"   Tools: customers_lookup, conversations_escalate_to_human, conversations_add_internal_note")
    print()

    # Example 3: Orchestrator Agent Tools
    print("3️⃣  Orchestrator Agent Toolsets")
    print("-" * 60)
    orchestrator_toolsets = manager.combine(["catalog", "customers", "conversations", "collab"])
    print(f"   Toolsets: {[type(t).__name__ for t in orchestrator_toolsets]}")
    print(f"   Usage: Agent(model, tools=manager.combine([...all...]))")
    print(f"   Tools: ALL tools from all toolsets")
    print()

    # Example 4: Getting individual toolsets
    print("4️⃣  Individual Toolset Access")
    print("-" * 60)
    catalog = manager.get("catalog")
    customers = manager.get("customers")
    print(f"   Catalog toolset: {type(catalog).__name__}")
    print(f"   Customers toolset: {type(customers).__name__}")
    print(f"   Direct combination: catalog + customers")
    print()

    # Example 5: Creating an agent (code only - won't run without API key)
    print("5️⃣  Creating an Agent (Example Code)")
    print("-" * 60)
    print("""
    from pydantic_ai import Agent
    from agents.registry import ToolsetManager
    from agents.deps import AgentDeps

    manager = ToolsetManager()

    agent = Agent(
        "openai:gpt-4o",
        deps_type=AgentDeps,
        system_prompt="You are a sales agent...",
        tools=manager.combine(["catalog", "customers"]),  # List of toolsets
    )
    """)
    print()

    print("=" * 60)
    print("✅ Examples completed!")
    print()
    print("💡 Key Takeaways:")
    print("   • ToolsetManager.combine() returns a list of toolsets")
    print("   • Pass the list directly to Agent(tools=[...])")
    print("   • Sales agents get catalog + customer tools")
    print("   • Support agents get customer + conversation tools")
    print("   • Orchestrators get all tools including collaboration")
    print("   • This keeps tool access controlled and agent-appropriate")


if __name__ == "__main__":
    main()
