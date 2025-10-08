# Examples

This directory contains examples demonstrating how to use the multi-agent system with Pydantic AI toolsets.

## Available Examples

### 1. Simple Agent (`simple_agent.py`)

Demonstrates the basics of creating an agent with toolsets.

**Shows:**
- Creating an agent with combined toolsets
- Setting up `AgentDeps` (dependencies)
- Running the agent with different queries
- How tools are automatically called by the LLM

**Run:**
```bash
uv run python -m examples.simple_agent
```

### 2. Toolset Composition (`toolset_composition.py`)

Shows how to create specialized agents using `ToolsetManager`.

**Shows:**
- Creating a sales agent (catalog + customers)
- Creating a support agent (customers + conversations)
- Creating an orchestrator agent (all tools)
- How to compose different tool combinations

**Run:**
```bash
uv run python -m examples.toolset_composition
```

## Understanding Toolsets

Our system organizes tools into domain-specific toolsets:

| Toolset | Prefix | Tools | Use Case |
|---------|--------|-------|----------|
| `catalog` | `catalog_` | `product_search`, `inventory_check` | Product browsing, inventory |
| `customers` | `customers_` | `lookup` | Customer information |
| `conversations` | `conversations_` | `escalate_to_human`, `add_internal_note` | Conversation management |
| `collab` | `collab_` | `handoff`, `consult` | Agent collaboration |

## Agent Patterns

### Pattern 1: Direct Toolset Combination

```python
from agents.toolsets.catalog import catalog_toolset
from agents.toolsets.customers import customers_toolset

agent = Agent(
    "openai:gpt-4o",
    deps_type=AgentDeps,
    tools=catalog_toolset + customers_toolset,  # Combine directly
)
```

### Pattern 2: ToolsetManager Composition

```python
from agents.registry import ToolsetManager

manager = ToolsetManager()
agent = Agent(
    "openai:gpt-4o",
    deps_type=AgentDeps,
    tools=manager.combine(["catalog", "customers"]),  # Compose by name
)
```

### Pattern 3: AgentExecutor (Production)

```python
from agents.executor import AgentExecutor

executor = AgentExecutor()
config = await executor.load_agent_config(business_id, "sales")
agent = executor.create_agent(config)  # Toolsets from DB config
```

## Testing Toolsets

See `tests/agents/tools/` for examples of testing individual toolset functions:

```python
from agents.toolsets.catalog import product_search
from unittest.mock import patch

async def test_product_search():
    with patch("agents.toolsets.catalog.search_products") as mock:
        mock.return_value = [...]
        result = await product_search(ctx, query="laptop")
        assert "laptop" in result.lower()
```

## Next Steps

1. Read the [Architecture Documentation](../docs/architecture/ARCHITECTURE.md)
2. Explore [Agent Collaboration Patterns](../docs/architecture/COLLABORATION.md)
3. Check out the [full agent configuration examples](../docs/architecture/AGENTS.md)

## Notes

⚠️ **Database Required**: Most examples require a running PostgreSQL database. They're designed to demonstrate code structure and patterns, not necessarily to run standalone.

💡 **API Keys**: Set your OpenAI API key: `export OPENAI_API_KEY=your-key`
