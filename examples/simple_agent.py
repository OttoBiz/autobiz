"""Simple example demonstrating how to use agents with toolsets.

This example shows how to create a customer service agent using our FunctionToolsets.
Includes Pydantic Logfire for observability and monitoring.

Prerequisites:
    1. Setup database: make db-setup
    2. Seed test data: make seed-db
    3. Set OPENAI_API_KEY environment variable
    4. (Optional) Configure Logfire for monitoring: https://logfire.pydantic.dev

Run with:
    uv run python -m examples.simple_agent
"""

import asyncio
from uuid import uuid4

import logfire
from pydantic_ai import Agent

from agents.deps import AgentDeps
from agents.toolsets.catalog import catalog_toolset
from agents.toolsets.customers import customers_toolset
from db.connection import close_db_pool, get_db_pool

# Configure Logfire for observability
logfire.configure()
logfire.instrument_pydantic_ai()


async def main():
    """Run a simple customer service agent with catalog and customer toolsets."""

    # Initialize database pool
    pool = await get_db_pool()

    # Get the seeded business from the database
    async with pool.acquire() as conn:
        business = await conn.fetchrow("SELECT id FROM businesses LIMIT 1")
        if not business:
            print("❌ No business found in database. Run 'make seed-db' first.")
            return
        business_id = business["id"]

        # Get a customer for testing
        customer = await conn.fetchrow("SELECT id FROM customer LIMIT 1")
        customer_id = customer["id"] if customer else uuid4()

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
        toolsets=[catalog_toolset, customers_toolset],  # Combine toolsets
    )

    # Set up dependencies (would normally come from the request context)
    deps = AgentDeps(
        business_id=business_id,
        conversation_id=uuid4(),
        customer_id=customer_id,
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
    print(f"Agent: {result.output}")
    print()

    # Example 2: Customer lookup
    print("Example 2: Customer Lookup")
    print("-" * 50)
    result = await agent.run(
        "Can you look up the customer with email john@example.com?",
        deps=deps,
    )
    print(f"Agent: {result.output}")
    print()

    # Example 3: Inventory check
    print("Example 3: Inventory Check")
    print("-" * 50)
    result = await agent.run(
        "Is product SKU-123 in stock?",
        deps=deps,
    )
    print(f"Agent: {result.output}")
    print()

    print("=" * 50)
    print("✅ Example completed!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\n💡 Make sure:")
        print("   1. Database is set up: make db-setup")
        print("   2. Test data is seeded: make seed-db")
        print("   3. OPENAI_API_KEY is set in your environment")
