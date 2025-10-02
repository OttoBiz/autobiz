"""Customer-facing AI agent with tools for handling customer inquiries."""

from pydantic_ai import Agent

from agents.deps import AgentDeps

# Initialize the customer service agent
customer_agent = Agent(
    "openai:gpt-4.1",  # Can be configured via environment
    deps_type=AgentDeps,
    system_prompt=(
        "You are a helpful customer service agent. "
        "You have access to tools to look up customer information, "
        "search products, check inventory, and escalate complex issues to humans. "
        "Always be polite, professional, and helpful. "
        "Use natural language and avoid technical jargon when responding to customers."
    ),
)
