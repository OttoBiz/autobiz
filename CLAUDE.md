# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working Protocol

**IMPORTANT: Always discuss before implementing**

For every task:
1. **First, discuss and clarify** what needs to be done
2. Read files, explore the codebase, check documentation, or search the internet as needed during discussion
3. **Only proceed with file changes when explicitly told to do so**

You may freely use Read, Glob, Grep, WebFetch, and WebSearch tools during discussions. Do NOT use Write, Edit, or Bash commands that modify files unless the user explicitly approves.

## Git Commit Guidelines

**Commit message format:**
Use conventional commit prefixes: `feat:`, `fix:`, `docs:`, `style:`, `refactor:`, `test:`, `chore:`

Examples:
- `feat: add product search tool for customer agent`
- `fix: handle null values in inventory check`
- `refactor: extract database connection to separate module`
- `docs: update API endpoint documentation`
- `chore: initialize project structure`

**Staging and committing:**
- Group related changes into logical commits
- Commit files together when changes are closely dependent (e.g., function created in one file and used in another)
- Group initialization or setup files together (e.g., multiple config files, initial directory structure)
- Avoid committing unrelated changes together

## Project Overview

AI-powered customer service platform (mini CRM) where businesses get dedicated agents to handle customer interactions, orders, payments, and shipping. Built with FastAPI, Pydantic AI, and PostgreSQL.

**Tech Stack:** FastAPI, Pydantic AI, PostgreSQL

## Architecture

### Request Flow
Customer message → Webhook → Agent Executor → Dynamic Agent + Tools → Response

### Key Principles
- **Multi-agent system**: Businesses can deploy multiple specialized AI agents (sales, support, legal intake, etc.)
- **Pydantic AI toolsets**: Tools organized in composable FunctionToolsets with prefixes (catalog_, customers_, etc.)
- **Simple composition**: ToolsetManager combines toolsets - no business logic, just composition
- **Conversation-centric state**: State lives in conversations, agents are stateless executors
- **Agent collaboration**: Agents can handoff (transfer control) or consult (ask for info) with each other
- **Minimal API surface**: Routes mainly for webhooks and business owner dashboard
- **Clear separation**: DB models, AI agents, and integrations are isolated

## Development Commands

**Install dependencies:**
```bash
uv sync
```

**Setup database:**
```bash
make db-setup
```

**Run development server:**
```bash
uv run uvicorn api.main:app --reload
```

**Run tests:**
```bash
uv run pytest
```

## Project Structure

### Core Directories

**[api/](api/)** - FastAPI endpoints
- [api/main.py](api/main.py) - FastAPI app initialization
- [api/routes/webhooks.py](api/routes/webhooks.py) - Customer messages from channels (WhatsApp, Telegram, etc.)
- [api/routes/businesses.py](api/routes/businesses.py) - Business owner dashboard endpoints
- [api/routes/admin.py](api/routes/admin.py) - Subscription/plan management
- Note: Webhooks also handle payment provider and shipping partner callbacks

**[agents/](agents/)** - Multi-agent system with Pydantic AI toolsets
- [agents/executor.py](agents/executor.py) - Multi-agent executor (loads agents from DB, composes toolsets)
- [agents/registry.py](agents/registry.py) - ToolsetManager (simple toolset composition)
- [agents/deps.py](agents/deps.py) - Agent dependencies (business_id, conversation_id, etc.)
- [agents/models.py](agents/models.py) - Structured output types (MessageResponse, HandoffResponse, etc.)
- [agents/toolsets/](agents/toolsets/) - Pydantic AI FunctionToolsets (prefixed):
  - [catalog.py](agents/toolsets/catalog.py) - catalog_* tools (product search, inventory)
  - [customers.py](agents/toolsets/customers.py) - customers_* tools (lookup, management)
  - [conversations.py](agents/toolsets/conversations.py) - conversations_* tools (messaging, escalation)
  - [collaboration.py](agents/toolsets/collaboration.py) - collab_* tools (handoff, consult)
  - [__init__.py](agents/toolsets/__init__.py) - ALL_TOOLS master toolset

**[db/](db/)** - Database layer
- [db/connection.py](db/connection.py) - PostgreSQL connection with asyncpg
- [db/queries/](db/queries/) - Domain-organized query functions (used by agent tools and API):
  - [agent.py](db/queries/agent.py) - Agent configuration queries
  - [business.py](db/queries/business.py) - Business queries
  - [customer.py](db/queries/customer.py) - Customer queries
  - [product.py](db/queries/product.py) - Product queries
  - [conversation.py](db/queries/conversation.py) - Conversation queries
  - [message.py](db/queries/message.py) - Message queries
- [db/models/](db/models/) - Pydantic models for type hints (one file per table)
- [db/schema/](db/schema/) - SQL schema files with version tracking

**[schemas/](schemas/)** - Pydantic schemas for request/response validation

**[integrations/](integrations/)** - External service integrations
- [integrations/channels/](integrations/channels/) - WhatsApp, Telegram, SMS providers
- [integrations/shipping/](integrations/shipping/) - Shipping partner APIs
- [integrations/payments/](integrations/payments/) - Payment provider APIs

**[config/](config/)** - Configuration and settings
- [config/settings.py](config/settings.py) - Environment variables

## Database Management

**Schema changes:**
1. Create new numbered SQL file in `db/schema/` (e.g., `004_add_column.sql`)
2. Include version tracking logic:
```sql
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_versions WHERE version = '004') THEN
        -- Your schema changes here
        ALTER TABLE users ADD COLUMN phone VARCHAR(50);

        INSERT INTO schema_versions (version, description)
        VALUES ('004', 'Add phone to users');

        RAISE NOTICE '✓ Schema 004 applied';
    ELSE
        RAISE NOTICE 'Schema 004 already applied, skipping...';
    END IF;
END $$;
```
3. Run `make db-setup` (automatically runs all `.sql` files in order)

**Tech notes:**
- Uses asyncpg (not SQLAlchemy ORM) - work with raw SQL queries
- Pydantic models in `db/models/` provide type hints for query results
- Each schema file is idempotent (safe to rerun)
- Python script (`db/schema/run_migrations.py`) runs all `.sql` files - no psql required

## Database Schema

Core tables:
1. Users - Platform users (can own multiple businesses, invite team members)
2. SubscriptionPlans - Subscription tiers with pricing and feature flags
3. Businesses - Registered businesses with subscription, settings, branding
4. **Agent** - Multi-agent configurations (business can have multiple agents with different keys)
5. Products - Business product catalog
6. Customers - End customers per business
7. Conversations - Customer conversation threads
8. Messages - Individual messages in conversations (serves as conversation history)

### Multi-Agent Schema Notes
- **Agent table**: Changed from 1:1 (business:agent) to 1:many (business can have multiple agents)
- Each agent has a `key` field for routing (e.g., "sales", "support", "legal")
- Each agent has a `name` field for display (e.g., "Legal Assistant Sarah")
- `tool_groups` JSONB field specifies which toolsets the agent can use
- `subagents` JSONB field lists agent keys this agent can transfer to
- Optional fields (personality, tone, greeting_message) stored in `metadata` JSONB

## Multi-Agent System & Toolsets

### How It Works

1. **Toolset Organization**: Tools are organized into Pydantic AI FunctionToolsets by domain
   - Each toolset file (catalog.py, customers.py, etc.) creates a FunctionToolset
   - Tools are registered using `@toolset.tool` decorator
   - All tools in a toolset share a common prefix (catalog_, customers_, etc.)

2. **Agent Configuration**: Agent configs stored in DB specify `tool_groups` (not individual tools)
   ```json
   {
     "key": "sales",
     "name": "Sales Assistant Sarah",
     "tool_groups": ["catalog", "customers", "collab"],
     "subagents": ["legal", "support"]
   }
   ```

3. **Toolset Composition**: When an agent is created, ToolsetManager combines the requested toolsets
   ```python
   toolset = manager.combine(["catalog", "customers", "collab"])
   agent = Agent(model, tools=toolset, ...)
   ```

4. **Execution**: Agent runs with the composed toolset

### Toolset Prefixing

All tools use prefixes to prevent naming collisions and provide context:

```python
# agents/toolsets/catalog.py
catalog_toolset = FunctionToolset()

@catalog_toolset.tool
async def product_search(...):  # Will be called catalog_product_search
    pass

@catalog_toolset.tool
async def inventory_check(...):  # Will be called catalog_inventory_check
    pass

# Export with prefix
catalog_toolset = catalog_toolset.prefix("catalog_")
```

**Benefits**:
- No naming collisions (orders.create vs conversations.create)
- Agent knows which domain a tool belongs to
- Easier to filter and organize tools
- Better context for the LLM

### ToolsetManager (Simple Composition)

The ToolsetManager is intentionally simple - no business logic, just composition:

```python
class ToolsetManager:
    def __init__(self):
        self.catalog = catalog_toolset
        self.customers = customers_toolset
        self.conversations = conversations_toolset
        self.collab = collaboration_toolset
        self.all_tools = ALL_TOOLS

    def get(self, name: str) -> AbstractToolset:
        """Get a single toolset by name"""
        return getattr(self, name, FunctionToolset())

    def combine(self, tool_groups: list[str]) -> AbstractToolset:
        """Combine multiple toolsets"""
        result = FunctionToolset()
        for group in tool_groups:
            result = result + self.get(group)
        return result
```

**No filtering, no business rules** - that happens elsewhere. This keeps the registry clean and focused.

### Agent Collaboration

**Handoff Pattern** (Transfer control):
- Used for: WRITE operations or complex GET operations
- Example: Sales agent hands off to legal intake agent for contract review
- Control transfers completely to the new agent
- Recorded in conversation state

**Consult Pattern** (Get information):
- Used for: Simple GET operations
- Example: Support agent consults pricing agent for product info
- Original agent maintains control
- Response is returned to the requesting agent

### Tool Organization

Tools are organized by business domain:
- **catalog/**: Product and inventory management
- **customers/**: Customer lookup and management
- **conversations/**: Messaging and escalation
- **orders/**: Order creation and payment processing
- **collaboration/**: Agent handoff and consult
- **internal/**: Platform tools (tagging, escalation)

### State Management

- **Conversation-centric**: State lives in conversations, not agents
- **Agents are stateless**: Agents are executors that operate on conversation state
- **Snapshots**: State can be snapshotted for pause/resume workflows
- **Follows Pydantic AI patterns**: Uses Pydantic AI's state persistence model
