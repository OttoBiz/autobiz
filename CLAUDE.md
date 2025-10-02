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

**Tech Stack:** FastAPI, Pydantic AI, PostgreSQL, Alembic (migrations)

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

**Run development server:**
```bash
uv run uvicorn api.main:app --reload
```

**Database migrations:**
```bash
uv run alembic revision --autogenerate -m "description"
uv run alembic upgrade head
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
- [db/connection.py](db/connection.py) - PostgreSQL connection setup
- [db/queries.py](db/queries.py) - Shared query functions (used by agent tools and API)
- [db/models/](db/models/) - SQLAlchemy models (one file per table):
  - [subscription.py](db/models/subscription.py) - Subscription/Plans
  - [business.py](db/models/business.py) - Businesses
  - [agent.py](db/models/agent.py) - Agent configurations
  - [channel.py](db/models/channel.py) - Communication channels (WhatsApp, etc.)
  - [product.py](db/models/product.py) - Products
  - [customer.py](db/models/customer.py) - Customers
  - [conversation.py](db/models/conversation.py) - Conversations
  - [message.py](db/models/message.py) - Messages

**[schemas/](schemas/)** - Pydantic schemas for request/response validation

**[integrations/](integrations/)** - External service integrations
- [integrations/channels/](integrations/channels/) - WhatsApp, Telegram, SMS providers
- [integrations/shipping/](integrations/shipping/) - Shipping partner APIs
- [integrations/payments/](integrations/payments/) - Payment provider APIs

**[config/](config/)** - Configuration and settings
- [config/settings.py](config/settings.py) - Environment variables

**[migrations/](migrations/)** - Alembic database migrations

## Database Schema

Each business gets a unique agent and customer base. Core tables:
1. Subscription/Plans - Platform subscription tiers
2. Businesses - Registered businesses
3. Agent - Per-business agent configurations
4. Channels - Communication channel settings (WhatsApp, Telegram, etc.)
5. Products - Business product catalog
6. Customers - End customers per business
7. Conversation - Customer conversation threads
8. Messages - Individual messages in conversations
