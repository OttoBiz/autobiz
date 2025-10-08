"""Simple example demonstrating how to use agents with toolsets.

This example shows how to create a customer service agent using our FunctionToolsets.

Run with:
    uv run python -m examples.simple_agent
"""

import asyncio
from uuid import uuid4

from pydantic_ai import Agent

from agents.deps import AgentDeps
from agents.toolsets.catalog import catalog_toolset
from agents.toolsets.customers import customers_toolset


async def main():
    """Run a simple customer service agent with catalog and customer toolsets."""

    # Create agent with toolsets
    agent = Agent(
        "openai:gpt-4o-mini",  # Use a cheaper model for the example
        deps_type=AgentDeps,
        system_prompt="""You are a helpful customer service agent for an e-commerce business.

You can:
- Look up customer information
- Search for products
- Check product inventory

Be friendly and helpful!""",
        tools=catalog_toolset + customers_toolset,  # Combine toolsets
    )

    # Set up dependencies (would normally come from the request context)
    deps = AgentDeps(
        business_id=uuid4(),
        conversation_id=uuid4(),
        customer_id=uuid4(),
    )

    print("🤖 Customer Service Agent Ready!")
    print("=" * 50)
    print()

    # Example 1: Product search
    print("Example 1: Product Search")
    print("-" * 50)
    result = await agent.run(
        "What laptops do you have available?",
        deps=deps,
    )
    print(f"Agent: {result.data}")
    print()

    # Example 2: Customer lookup
    print("Example 2: Customer Lookup")
    print("-" * 50)
    result = await agent.run(
        "Can you look up the customer with email john@example.com?",
        deps=deps,
    )
    print(f"Agent: {result.data}")
    print()

    # Example 3: Inventory check
    print("Example 3: Inventory Check")
    print("-" * 50)
    result = await agent.run(
        "Is product SKU-123 in stock?",
        deps=deps,
    )
    print(f"Agent: {result.data}")
    print()

    print("=" * 50)
    print("✅ Example completed!")


if __name__ == "__main__":
    # Note: This will fail without a real database connection
    # This is just to demonstrate the agent setup
    print("⚠️  Note: This example requires a database connection to work.")
    print("    It's meant to demonstrate the code structure.\n")

    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nThis is expected - the example needs a real database.")
        print("Check the code to see how to structure agents with toolsets!")
