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
Customer message → Webhook → AI Agent → Tools (DB access) → Response

### Key Principles
- **Agent-centric**: Most business logic handled by AI agents using tools
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

**[agents/](agents/)** - AI agents with direct DB access via tools
- [agents/base.py](agents/base.py) - Base agent configuration (Pydantic AI)
- [agents/customer_agent.py](agents/customer_agent.py) - Main customer-facing agent
- [agents/tools/](agents/tools/) - Agent tools that perform DB operations:
  - [products.py](agents/tools/products.py) - Product search/information
  - [orders.py](agents/tools/orders.py) - Order creation/management
  - [payments.py](agents/tools/payments.py) - Payment request triggers
  - [shipping.py](agents/tools/shipping.py) - Shipping partner coordination
  - [inventory.py](agents/tools/inventory.py) - Inventory checks/updates
  - [customers.py](agents/tools/customers.py) - Customer data access

**[db/](db/)** - Database layer
- [db/connection.py](db/connection.py) - PostgreSQL connection with asyncpg
- [db/queries.py](db/queries.py) - Shared query functions (used by agent tools and API)
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
4. Agent - Per-business agent configurations
5. Channels - Communication channel settings (WhatsApp, Telegram, etc.)
6. Products - Business product catalog
7. Customers - End customers per business
8. Conversations - Customer conversation threads
9. Messages - Individual messages in conversations
