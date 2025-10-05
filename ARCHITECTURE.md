# Architecture Overview

## Vision

A multi-agent AI platform where businesses can deploy specialized AI teammates for various business functions. Not just customer service, but sales, intake, scheduling, research, and custom workflows.

## Core Concepts

### Multi-Agent System
- **Business → Multiple Agents** (1:many relationship)
- Each agent is a specialized AI teammate with specific role, tools, and channels
- Agents operate independently but share business context and customer data

### Agent Types
- **Customer Service**: Product questions, order tracking, support tickets
- **Sales Assistant**: Lead qualification, demos, proposals
- **Legal Intake**: Case collection, document gathering, scheduling
- **Appointment Scheduler**: Calendar management, booking, reminders
- **Research Assistant**: Information gathering, analysis
- **Custom**: Fully configurable for unique business needs

### Tool-Based Architecture
- Agents use **tools** to interact with data and external systems
- Tools are modular and composable (mix/match per agent)
- Tools have direct database access via `db/queries.py`
- Tool categories: E-commerce, Service-based, Universal, Custom

## Agent Definition Format

Inspired by Claude Code subagents, using YAML-like structure stored in JSONB:

```yaml
---
name: customer-support-agent
description: Handles customer inquiries, order tracking, and product questions
type: customer_service
model: claude-sonnet-4.5
tools:
  - product_search
  - order_lookup
  - inventory_check
  - send_message
  - create_ticket
channels:
  - whatsapp
  - telegram
active_hours: "9am-5pm EST"
escalation_rules:
  - condition: "refund_request > $500"
    action: "notify_human"
---

You are a friendly customer support agent for {business_name}.

Your role:
- Answer product questions using the product catalog
- Help customers track their orders
- Check inventory availability
- Escalate complex issues to human staff

Tone: Professional but warm
Response time: Aim for under 2 minutes
```

### Example: Legal Intake Agent

```yaml
---
name: legal-intake-agent
description: Collects initial case information from potential clients
type: legal_intake
model: claude-sonnet-4.5
tools:
  - case_creation
  - document_upload
  - appointment_booking
  - customer_lookup
  - send_message
channels:
  - website_chat
  - email
specialization: "family_law"
---

You are a legal intake specialist for {business_name}, a family law practice.

Your responsibilities:
- Gather initial case details (names, dates, issue type)
- Collect necessary documents
- Schedule consultation with appropriate attorney
- Screen for conflicts of interest
- Explain fee structures

Important: You are NOT providing legal advice. Always clarify you're collecting information for an attorney to review.

Tone: Empathetic, professional, confidential
```

## Database Schema

### Current State (What We Have)

**agent** - Single AI agent per business (1:1 relationship)
```sql
-- Current schema (004_create_agent.sql)
business_id UUID UNIQUE      -- ⚠️ Only one agent per business
name VARCHAR(255)
avatar_url VARCHAR(500)
personality TEXT
tone VARCHAR(100)
system_prompt TEXT
greeting_message TEXT
conversation_rules JSONB
channels JSONB              -- WhatsApp, webchat, SMS, email configs
status VARCHAR(50)
version INTEGER
```

**businesses** - Business accounts with subscriptions
**customers** - End customers per business
**products** - Product catalog (e-commerce)
**conversations** - Customer message threads
**messages** - Individual messages

**Existing Tools** (currently tied to single `customer_agent`):
- [agents/tools/products.py](agents/tools/products.py) - `product_search`, `product_check_inventory`
- [agents/tools/customers.py](agents/tools/customers.py) - `customer_lookup`
- [agents/tools/conversations.py](agents/tools/conversations.py) - Conversation management

### Target State (Multi-Agent System)

**agents** (renamed from `agent`, breaking changes)
```sql
-- Migration needed: Remove UNIQUE constraint on business_id
business_id UUID             -- ✅ Multiple agents per business
name VARCHAR(255)
agent_type VARCHAR(100)      -- NEW: customer_service, sales, legal_intake, custom
description TEXT             -- NEW: When this agent should be invoked

-- Consolidate config into single JSONB
config JSONB NOT NULL        -- NEW: Stores full agent configuration
/*
Example config structure:
{
  "model": "claude-sonnet-4.5",
  "system_prompt": "You are a...",
  "tools": ["product_search", "order_lookup"],
  "channels": ["whatsapp", "telegram"],
  "active_hours": "9am-5pm EST",
  "escalation_rules": [...],
  "personality": "friendly",
  "tone": "professional",
  "greeting_message": "Hello!",
  "conversation_rules": {...}
}
*/

-- Usage tracking (NEW)
total_tokens_used BIGINT DEFAULT 0
last_active_at TIMESTAMPTZ

-- Keep existing
status VARCHAR(50)
version INTEGER
created_at, updated_at
```

**tool_registry** (NEW TABLE)
```sql
id UUID PRIMARY KEY
name VARCHAR(100) UNIQUE     -- e.g., "product_search"
category VARCHAR(50)         -- ecommerce, service, universal, payment
description TEXT
required_tables TEXT[]       -- DB dependencies
is_system BOOLEAN            -- System vs custom tools
code_path VARCHAR(255)       -- e.g., "agents.tools.ecommerce.product_search"
parameters_schema JSONB      -- Tool parameter definitions
created_at TIMESTAMPTZ
```

**conversations** (UPDATE - Multi-handler support)
```sql
-- Existing columns stay
-- NEW columns:
-- Universal handler tracking (replaces simple agent_id)
current_handler_type VARCHAR(50) DEFAULT 'agent'  -- 'agent', 'human', 'system'
current_handler_id UUID                           -- agent_id or user_id
initial_agent_id UUID REFERENCES agents(id)       -- Which agent started conversation

-- Handoff tracking
total_handoffs INT DEFAULT 0
last_handoff_at TIMESTAMPTZ

-- Token tracking
total_tokens_used BIGINT DEFAULT 0

-- Aggregate stats
total_messages INT DEFAULT 0
total_escalations INT DEFAULT 0
last_message_at TIMESTAMPTZ
closed_at TIMESTAMPTZ

-- Indexes
CREATE INDEX idx_current_handler ON conversations(current_handler_type, current_handler_id);
CREATE INDEX idx_business_conversations ON conversations(business_id, created_at);
```

**messages** (UPDATE - Universal tagging system)
```sql
-- Existing columns stay
-- NEW columns:
sender_type VARCHAR(50)            -- customer, agent, human, system
sender_id UUID                     -- agent_id or user_id

-- Universal tagging (agents can tag agents, humans, or teams)
tagged_entity_type VARCHAR(50)     -- 'agent', 'human', 'team', NULL
tagged_entity_id UUID              -- agent_id, user_id, or team_id
is_internal_note BOOLEAN DEFAULT false
parent_message_id UUID             -- Thread/reply tracking

-- Processing
processed_by_tagged_entity BOOLEAN DEFAULT false

-- Token tracking
input_tokens INT
output_tokens INT
total_tokens INT

-- Tool usage
tools_used JSONB                   -- Which tools were called
```

**escalation_history** (NEW TABLE - Track escalation lifecycle)
```sql
id UUID PRIMARY KEY
conversation_id UUID REFERENCES conversations(id)

escalation_type VARCHAR(50)        -- refund_request, angry_customer, technical, etc.
reason TEXT
triggered_by VARCHAR(50)           -- 'agent_rule', 'customer_request', 'agent_uncertainty'

-- State machine
status VARCHAR(50)                 -- pending, in_progress, resolved, cancelled
assigned_to UUID REFERENCES users(id)

-- Timing
escalated_at TIMESTAMPTZ DEFAULT NOW()
picked_up_at TIMESTAMPTZ          -- When human started handling
resolved_at TIMESTAMPTZ

-- Resolution
resolution_notes TEXT

-- Indexes
CREATE INDEX idx_conversation_escalations ON escalation_history(conversation_id);
CREATE INDEX idx_assigned_escalations ON escalation_history(assigned_to, status);
```

**handoff_history** (NEW TABLE - Track agent/human handoffs)
```sql
id UUID PRIMARY KEY
conversation_id UUID REFERENCES conversations(id)

from_type VARCHAR(50)              -- 'agent', 'human'
from_id UUID                       -- Who initiated handoff

to_type VARCHAR(50)                -- 'agent', 'human'
to_id UUID                         -- Who received handoff

reason TEXT
handoff_message TEXT               -- Instructions passed during handoff

created_at TIMESTAMPTZ DEFAULT NOW()

-- Indexes
CREATE INDEX idx_conversation_handoffs ON handoff_history(conversation_id);
CREATE INDEX idx_agent_handoffs ON handoff_history(to_type, to_id);
```

**token_usage** (NEW TABLE - for billing)
```sql
id UUID PRIMARY KEY
business_id UUID REFERENCES businesses(id)
agent_id UUID REFERENCES agents(id)
conversation_id UUID REFERENCES conversations(id)
tokens_used BIGINT NOT NULL
model_used VARCHAR(100)
cost_usd DECIMAL(10,6)
period_month VARCHAR(7)      -- "2025-10" for monthly aggregation
created_at TIMESTAMPTZ

-- Indexes
CREATE INDEX idx_token_usage_business_month ON token_usage(business_id, period_month);
CREATE INDEX idx_token_usage_agent ON token_usage(agent_id);
```

**subscription_plans** (ADD COLUMNS)
```sql
-- Existing columns stay
-- NEW columns:
max_agents INT NOT NULL
included_tokens BIGINT
overage_rate_per_1k DECIMAL(10,4)
max_channels_per_agent INT
```

### Future Tables (Service-Based Businesses)

**services** - Service catalog (parallel to products)
- For law firms, consultancies, agencies
- Fields: name, description, duration, pricing, expertise_required

**appointments** - Scheduled sessions (parallel to orders)
- For booking consultations, meetings
- Fields: service_id, scheduled_time, duration, status

**cases** - Legal cases, projects
- For tracking ongoing client work
- Fields: case_type, status, priority, intake_data (JSONB)

## Tool System

### Current Tool Implementation

**Existing tools** (as Pydantic AI tools, tied to `customer_agent`):

**[agents/tools/products.py](agents/tools/products.py)**
```python
@customer_agent.tool
async def product_search(ctx: RunContext[AgentDeps], query: str, limit: int = 5):
    """Search for products by name or description"""
    products = await search_products(ctx.deps.business_id, query, limit)
    # Returns formatted product list

@customer_agent.tool
async def product_check_inventory(ctx: RunContext[AgentDeps], sku: str):
    """Check inventory for specific SKU"""
    product = await get_product_by_sku(ctx.deps.business_id, sku)
    # Returns stock status
```

**[agents/tools/customers.py](agents/tools/customers.py)**
```python
@customer_agent.tool
async def customer_lookup(ctx: RunContext[AgentDeps], email: str | None, phone: str | None):
    """Find customer by contact info"""
    customer = await find_customer_by_contact(ctx.deps.business_id, email, phone)
    # Returns customer profile
```

**[agents/tools/conversations.py](agents/tools/conversations.py)**
- Conversation management tools

### Target Tool System

**Tool Registry Pattern** - Convert existing tools to be agent-agnostic:

```python
# agents/tools/ecommerce/product_search.py
class ProductSearchTool:
    """Registerable tool for product search"""

    name = "product_search"
    category = "ecommerce"
    description = "Search for products in business catalog"
    required_tables = ["products"]

    class Parameters(BaseModel):
        query: str
        limit: int = 10

    @staticmethod
    async def execute(business_id: str, query: str, limit: int = 10):
        """Execute tool - uses db/queries.py"""
        products = await search_products(business_id, query, limit)
        return format_product_results(products)
```

**Tool Categories** (Future):

**E-commerce Tools:**
- ✅ `product_search` - Search product catalog (exists)
- ✅ `product_check_inventory` - Check stock levels (exists)
- 🔲 `order_lookup` - Find order details
- 🔲 `order_create` - Create new order
- 🔲 `shipping_tracking` - Track shipments

**Service Tools** (for service-based businesses):
- 🔲 `service_catalog` - Browse available services
- 🔲 `appointment_booking` - Schedule appointments
- 🔲 `case_creation` - Create new cases/projects
- 🔲 `document_upload` - Handle document collection

**Universal Tools:**
- ✅ `customer_lookup` - Find customer information (exists)
- 🔲 `send_message` - Send messages to customers
- 🔲 `create_ticket` - Escalate to human staff
- 🔲 `conversation_history` - Retrieve past interactions

**Collaboration Tools** (agent-to-agent, agent-to-human):
- 🔲 `handoff_to_agent` - Transfer conversation to another agent
- 🔲 `handoff_to_human` - Escalate to human staff
- 🔲 `consult_agent` - Ask another agent for help (internal)
- 🔲 `consult_human` - Ask human for guidance (internal)
- 🔲 `notify_human` - Soft escalation (notify but keep handling)

**Payment Tools:**
- 🔲 `payment_request` - Generate payment links
- 🔲 `payment_status` - Check payment status

### Dynamic Tool Loading (Target)

```python
# agents/tools/registry.py
class ToolRegistry:
    _tools: Dict[str, Type] = {}

    @classmethod
    def register(cls, tool_class):
        cls._tools[tool_class.name] = tool_class
        return tool_class

    @classmethod
    def load_tools_for_agent(cls, tool_names: List[str]):
        return [cls._tools[name] for name in tool_names]

# At runtime:
agent_config = {"tools": ["product_search", "customer_lookup"]}
tools = ToolRegistry.load_tools_for_agent(agent_config['tools'])
```

## Request Flow

### Customer Message Flow

```
1. Message arrives via webhook (WhatsApp, Telegram, etc.)
2. Identify conversation and assigned agent
3. Load agent configuration from database
4. Load agent's available tools
5. Build system prompt with business context
6. Execute Pydantic AI with tools
7. Track token usage for billing
8. Check escalation rules
9. Send response via channel
10. Store message and update conversation
```

### Agent Selection Logic

```
Message arrives →
  - Existing conversation? → Use current handler (agent or human)
  - New conversation → Route based on:
    - Channel mapping (WhatsApp → Support, Email → Sales)
    - Keyword/intent detection
    - Business routing rules
    - Default agent fallback
```

## Collaboration & Escalation Workflows

### Core Concepts

**Multi-Handler System**: Conversations can be handled by:
- **Agents** (AI teammates)
- **Humans** (business staff)
- Seamless handoffs between them

**Universal Tagging**: Any participant can tag any other:
- Human tags agent: "@sales-agent follow up on this lead"
- Agent tags human: "@sarah need approval for $500 refund"
- Agent tags agent: "@legal-agent check terms compliance"
- Human tags human: "@john can you handle this VIP customer?"

### Workflow Examples

#### 1. Agent-to-Agent Handoff

**Scenario**: Customer service agent detects sales opportunity

```
Customer: "I need 100 units, what's bulk pricing?"
customer-service-agent: [detects sales opportunity, uses handoff_to_agent tool]

System:
- Creates handoff_history record
- Updates conversation.current_handler_id = sales_agent_id
- Passes context: "Customer interested in bulk purchase (100 units)"

sales-agent: [receives handoff, continues conversation]
"For 100 units, we offer 15% discount. Let me prepare a quote..."
```

**Agent config with handoff capability:**
```yaml
---
name: customer-service-agent
tools:
  - product_search
  - customer_lookup
  - handoff_to_agent
collaboration_rules:
  can_handoff_to:
    - sales-agent
    - technical-support-agent
  auto_handoff_triggers:
    - condition: "bulk_order_inquiry"
      handoff_to: "sales-agent"
---
```

#### 2. Agent-to-Human Escalation

**Scenario**: Refund request over threshold

```
Customer: "I want a refund for order #12345"
customer-service-agent: [checks order: $750, over $500 threshold]
agent: [uses handoff_to_human tool with reason "refund_over_threshold"]

System:
- Creates escalation_history record (status: pending)
- Updates conversation.current_handler_type = 'human'
- Notifies Sarah (support manager)
- Agent stops responding

Sarah: [receives notification, reviews]
Sarah: "Refund approved. Order was defective."

System:
- Updates escalation_history (status: resolved)
- Can hand back to agent or human continues
```

#### 3. Agent Consultation (Internal Collaboration)

**Scenario**: Sales agent needs inventory info from support agent

```
Customer: "What's lead time for custom orders?"
sales-agent: [doesn't have this info, uses consult_agent tool]

Internal message (customer doesn't see):
sales-agent → support-agent: "@support-agent what's lead time for custom orders?"

support-agent: [processes internal consultation]

Internal response:
support-agent → sales-agent: "Custom orders: 2-3 weeks production + shipping"

sales-agent: [receives answer, responds to customer]
"Custom orders take 2-3 weeks for production plus shipping time."

Note: Conversation handler never changed, just internal collaboration
```

#### 4. Human Orchestration

**Scenario**: Business owner orchestrates multi-agent workflow

```
Customer: "I need a custom legal contract for bulk purchase"
[Conversation starts with sales-agent]

Owner (monitoring dashboard):
1. Tags legal agent: "@legal-agent draft standard bulk purchase agreement"
   - legal-agent generates draft (internal)

2. Tags compliance agent: "@compliance-agent review for regulatory compliance"
   - compliance-agent reviews (internal)

3. Tags sales agent: "@sales-agent contract approved, send to customer"
   - sales-agent sends to customer

All internal collaboration, customer just sees smooth process
```

#### 5. Soft Escalation (Notify Human)

**Scenario**: High-value customer, notify human but agent continues

```
Customer: "Hi, I'm interested in your enterprise plan"
sales-agent: [detects VIP inquiry, uses notify_human tool]

System:
- Sends notification to sales manager: "Enterprise inquiry from new customer"
- Creates internal note in conversation
- Agent CONTINUES handling conversation
- Human can monitor and intervene if needed

sales-agent: "Great! Our enterprise plan includes..."

Sales Manager: [monitoring, decides to join]
Manager: [takes over or sends guidance to agent]
```

### Message Routing Logic

```python
async def route_message(message: Message, conversation: Conversation):
    """Intelligent message routing"""

    # 1. Tagged message (highest priority)
    if message.tagged_entity_type and message.tagged_entity_id:
        return await route_to_tagged_entity(message)

    # 2. Customer message → current handler
    if message.sender_type == "customer":
        if conversation.current_handler_type == "agent":
            return await invoke_agent(conversation.current_handler_id, message)
        elif conversation.current_handler_type == "human":
            return await notify_human(conversation.current_handler_id, message)

    # 3. Internal messages (agent/human collaboration)
    # Already handled by tagging logic
```

### Handoff vs Consult: Clear Decision Framework

**Critical System Design**: To prevent confusion and maintain reliable operation, handoff and consult have strict, enforceable boundaries.

#### Mental Model: CONSULT = GET, HANDOFF = WRITE (+ Complex GET)

**CONSULT** - Read operations (idempotent, single-turn)
```
✓ Simple data lookup
✓ Policy/rule checking
✓ Quick calculations
✓ One question → one answer
✓ Agent continues after getting answer

Examples:
- "What's inventory count for SKU-123?" → GET data
- "What's our return policy?" → GET knowledge
- "Can we offer net-30 terms?" → GET approval/rule
- "What's shipping cost to ZIP 12345?" → GET calculation
```

**HANDOFF** - Write operations + Complex/Interactive reads
```
✓ Any state change (orders, refunds, updates)
✓ Complex reads requiring multi-turn dialogue
✓ Reads requiring customer interaction with specialist
✓ Changes conversation ownership
✓ Original agent stops responding

Examples:
- "Process this refund" → WRITE operation
- "Create this order" → WRITE operation
- "Design enterprise architecture for customer" → Complex GET (multi-turn)
- "Which product fits customer's specific needs?" → Interactive GET
```

#### Hard Rules (System-Enforced)

**HANDOFF** - Changes conversation ownership
```
✓ Different domain of responsibility (sales → support → legal)
✓ Requires different toolset
✓ Requires sustained engagement (multiple turns)
✓ Customer explicitly requests different service
✓ Current agent lacks authority/capability

Result:
→ conversation.current_handler_id CHANGES
→ Original agent stops responding
→ New handler takes over completely
→ Creates handoff_history record
```

**CONSULT** - Temporary information request
```
✓ Single question/answer within current domain
✓ Agent can continue after getting answer
✓ No customer-visible change needed
✓ Quick fact-checking or data lookup (< 50 words)

Result:
→ conversation.current_handler_id UNCHANGED
→ Original agent still owns conversation
→ Consulting agent responds internally only
→ Creates internal message (is_internal_note=true)
```

#### Decision Matrix

| Scenario | Type | Action | Reason |
|----------|------|--------|--------|
| "What's inventory count for SKU-123?" | Simple GET | **CONSULT** → inventory-agent | One-shot data lookup |
| "Process this refund" | WRITE | **HANDOFF** → refund-agent | Changes order state |
| "What's best product for customer's needs?" | Interactive GET | **HANDOFF** → product-specialist | Needs multi-turn dialogue with customer |
| "Can we offer 20% discount?" | Simple GET | **CONSULT** → manager | Policy/approval lookup |
| "Create custom pricing proposal" | WRITE | **HANDOFF** → sales-specialist | Creates artifact + requires expertise |
| "What's shipping cost to ZIP 12345?" | Simple GET | **CONSULT** → shipping-agent | Calculation, no interaction needed |
| "Design enterprise solution for customer" | Complex GET | **HANDOFF** → architect-agent | Requires expertise + customer collaboration |
| "What's our return policy?" | Simple GET | **CONSULT** → legal-agent | Static knowledge lookup |
| "Negotiate contract terms" | WRITE | **HANDOFF** → legal-agent | Changes agreement + multi-turn |
| Customer says "I want to speak to sales" | N/A | **HANDOFF** → sales-agent | Explicit customer request |

#### Decision Tree

```
Does it change system state (create order, process refund, etc)?
├─ YES → HANDOFF (WRITE operation)
└─ NO → Is it a simple data lookup?
    ├─ YES → CONSULT (Simple GET)
    └─ NO → Does customer need to interact with specialist?
        ├─ YES → HANDOFF (Interactive GET)
        └─ NO → Will it require multiple exchanges?
            ├─ YES → HANDOFF (Complex GET)
            └─ NO → CONSULT (Simple GET)
```

#### Golden Rules

**Primary Rule (Technical):**
> **"Does it READ or WRITE?"**
> - **Simple READ** → CONSULT
> - **WRITE or Complex READ** → HANDOFF

**Secondary Rule (User-facing):**
> **"Will the OTHER agent need to talk to the customer?"**
> - **YES** → HANDOFF
> - **NO** → CONSULT

#### Tool Implementation with Built-in Validation

**HandoffToAgentTool**:
```python
class HandoffToAgentTool:
    name = "handoff_to_agent"

    class Parameters(BaseModel):
        target_agent_id: str
        reason: str  # REQUIRED: Must be valid reason
        context: str  # What target agent needs to know

        @validator('reason')
        def validate_reason(cls, v):
            valid_reasons = [
                'domain_change',      # Different area of expertise
                'capability_gap',     # Need different tools
                'authority_limit',    # Need higher approval
                'customer_request',   # Customer explicitly asked
                'multi_turn_needed'   # Requires sustained engagement
            ]
            if v not in valid_reasons:
                raise ValueError(f"Invalid reason. Must be: {valid_reasons}")
            return v

    @staticmethod
    async def execute(...):
        """
        ⚠️ Use this when:
        - Customer needs different type of service
        - You don't have the tools/authority to continue
        - Customer explicitly requests different agent
        - Requires multiple exchanges outside your domain

        ❌ DON'T use for:
        - Quick data lookup (use consult_agent instead)
        - Single question that doesn't change flow
        """
        # Validates handoff is appropriate
        # Changes conversation.current_handler_id
        # Current agent stops responding
```

**ConsultAgentTool**:
```python
class ConsultAgentTool:
    name = "consult_agent"

    class Parameters(BaseModel):
        target_agent_id: str
        question: str  # REQUIRED: Specific question < 50 words

        @validator('question')
        def validate_question(cls, v):
            if len(v.split()) > 50:
                raise ValueError("Consult questions must be concise (< 50 words)")
            if not any(w in v.lower() for w in ['what', 'when', 'how', 'is', 'can']):
                raise ValueError("Must be a specific question")
            return v

    @staticmethod
    async def execute(...):
        """
        ✅ Use this when:
        - You need a specific piece of information
        - You can continue after getting the answer
        - It's a one-time lookup, not ongoing dialogue

        ❌ DON'T use if:
        - Other agent needs to take over (use handoff_to_agent)
        - Question requires multiple exchanges
        - Customer needs to interact with other agent
        """
        # Creates internal message (is_internal_note=true)
        # conversation.current_handler_id UNCHANGED
        # Returns answer, consulting agent continues
```

#### System Validation & Monitoring

**Prevent Misuse:**
```python
async def validate_handoff(current_agent_id, target_agent_id, reason):
    """Prevent inappropriate handoffs"""

    # 1. Detect if consult would be better
    if reason in ['quick_question', 'data_lookup', 'fact_check']:
        raise ValidationError(
            "This should be a CONSULT, not a HANDOFF. "
            "Use consult_agent for quick information requests."
        )

    # 2. Prevent handoff to same agent type
    if current_agent.type == target_agent.type:
        raise ValidationError("Handoff to same type not allowed")

    # 3. Check if handoff is in allowed list
    if target_agent_id not in current_agent.config['can_handoff_to']:
        raise ValidationError(f"Not configured to hand off to {target_agent_id}")

async def validate_consult(current_agent_id, target_agent_id, question):
    """Prevent inappropriate consults"""

    # 1. Detect if handoff would be better
    if len(question.split()) > 50:
        raise ValidationError(
            "Question too complex. Use handoff_to_agent for multi-turn."
        )

    # 2. Prevent consult loops
    if await is_consultation_loop(current_agent_id, target_agent_id):
        raise ValidationError("Consultation loop detected")
```

**Pattern Detection:**
```python
# Alert on problematic patterns

# Pattern 1: Handoff ping-pong (should have been consult)
sales-agent → support-agent (handoff)
support-agent → sales-agent (handoff back after 1 message)
⚠️ Alert: This should have been a CONSULT

# Pattern 2: Excessive consults (should have been handoff)
sales-agent → support-agent (consult #1)
sales-agent → support-agent (consult #2)
sales-agent → support-agent (consult #3)
⚠️ Alert: Consider HANDOFF for ongoing back-and-forth

# Pattern 3: Consult becomes multi-turn (should escalate to handoff)
sales-agent: consult("What's lead time?")
support-agent: "Need more details, what product?"
⚠️ Alert: This became multi-turn, should HANDOFF
```

#### Agent System Prompt Guidance

Each agent receives this in their system prompt:

```
## When to HANDOFF vs CONSULT

HANDOFF (use handoff_to_agent tool):
- Customer's needs changed to a different domain
- You lack the tools or authority to continue
- Customer explicitly requests different agent/person
- Requires multiple back-and-forth exchanges outside your expertise

CONSULT (use consult_agent tool):
- You need a specific piece of information
- A quick question another agent can answer
- You will continue the conversation after
- Customer doesn't need to know you asked

GOLDEN RULE:
- Other agent talks to customer? → HANDOFF
- You just need information? → CONSULT
```

### Escalation State Machine

```
Conversation Lifecycle:

[agent handling] → [escalation trigger] → [human_pending]
                                              ↓
                                         [human_active]
                                              ↓
                                    [resolved/cancelled]
                                              ↓
                                      [back to agent]
```

**State Transitions:**
- `agent` → `human_pending`: Escalation created, waiting for human pickup
- `human_pending` → `human_active`: Human accepts and starts handling
- `human_active` → `resolved`: Human resolves issue
- `resolved` → `agent`: Conversation handed back to agent

### Agent Configuration with Collaboration

```yaml
---
name: sales-agent
type: sales
model: claude-sonnet-4.5
tools:
  - product_search
  - customer_lookup
  - handoff_to_agent
  - handoff_to_human
  - consult_agent

collaboration_rules:
  # Which agents this agent can hand off to
  can_handoff_to:
    - customer-service-agent
    - legal-intake-agent

  # Which agents this agent can consult
  can_consult:
    - support-agent
    - inventory-agent
    - legal-agent

  # Automatic escalation rules
  escalation_rules:
    - condition: "contract_negotiation"
      action: "handoff_to_human"
      notify: "sales_manager"
    - condition: "enterprise_inquiry"
      action: "notify_human"
      notify: "sales_manager"

  # Automatic handoff rules
  auto_handoffs:
    - condition: "technical_issue"
      handoff_to: "technical-support-agent"
    - condition: "billing_question"
      handoff_to: "customer-service-agent"
---

You are a sales agent for {business_name}...
```

## State Management

### Philosophy: Conversation-Centric State

**Key Principle**: Agents are **stateless executors**. State lives in conversations.

```
STATE (what we track):
✓ Conversation (who's handling, context, status)
✓ Business quotas (token limits, usage)

NOT STATE (ephemeral, doesn't need tracking):
✗ Agent execution (they run, they finish, they're done)
✗ Individual tool calls (logged for analytics, not state)
```

### Influenced by Pydantic AI Graph Pattern

Our state management follows [Pydantic AI's state persistence pattern](https://ai.pydantic.dev/graph/#state-persistence):

- **Conversations = Pydantic AI Runs**: Can be interrupted and resumed
- **State Snapshots**: Save state at each turn for pause/resume
- **Interruption-friendly**: Built for workflows that need to wait (consults, human approval)

### State Architecture

```
┌─────────────────────────────────────────────────┐
│         Redis (Hot Cache)                        │
│  - Latest conversation snapshot (1 hour TTL)     │
│  - Temporary locks (handoffs, consults)          │
│  - Token usage counters                          │
│  - Rate limit tracking                           │
└─────────────────────────────────────────────────┘
                     ↕
┌─────────────────────────────────────────────────┐
│         PostgreSQL (Source of Truth)             │
│  - conversation_snapshots (full history)         │
│  - conversations (current state)                 │
│  - messages (all messages)                       │
│  - handoff_history, escalation_history           │
│  - token_usage (billing)                         │
└─────────────────────────────────────────────────┘
```

### State Models

```python
# state/models.py

class ConversationState(BaseModel):
    """
    Conversation state (aligned with Pydantic AI pattern).
    This is what gets saved in snapshots.
    """

    # Identity
    conversation_id: UUID
    business_id: UUID
    customer_id: UUID

    # Handler (who's managing this run)
    current_handler_type: str  # 'agent', 'human'
    current_handler_id: UUID

    # Context (the "memory" for resumption)
    messages: list[Message]  # Full message history

    # Interruption state (key for pause/resume!)
    is_interrupted: bool = False
    interrupted_reason: str | None = None  # 'awaiting_consult', 'awaiting_human', 'handoff'
    awaiting_response_from: UUID | None = None

    # Metadata
    created_at: datetime
    last_activity_at: datetime
    total_tokens_used: int


class StateSnapshot(BaseModel):
    """Point-in-time snapshot of conversation state"""
    state: ConversationState
    timestamp: datetime
    snapshot_id: UUID


class BusinessQuotaState(BaseModel):
    """Token usage and limits for a business"""
    business_id: UUID
    current_month: str  # "2025-10"

    tokens_used_this_month: int
    tokens_limit: int
    tokens_remaining: int

    active_agents_count: int
    max_agents_allowed: int
```

### State Persistence

```python
# state/persistence.py

class ConversationStatePersistence:
    """
    PostgreSQL-backed state persistence.
    Follows Pydantic AI's BaseStatePersistence pattern.
    """

    def __init__(self, db_pool, redis_client):
        self.db = db_pool
        self.redis = redis_client

    async def save(self, snapshot: StateSnapshot):
        """Save conversation state snapshot after each turn"""

        conversation_id = snapshot.state.conversation_id

        # 1. Save to DB (full history)
        await self.db.execute(
            """
            INSERT INTO conversation_snapshots (
                conversation_id, snapshot_data, created_at
            ) VALUES ($1, $2, NOW())
            """,
            conversation_id,
            snapshot.model_dump_json()
        )

        # 2. Update Redis cache (latest only)
        await self.redis.setex(
            f"conv:{conversation_id}:latest",
            3600,  # 1 hour TTL
            snapshot.model_dump_json()
        )

    async def load_latest(self, conversation_id: UUID) -> Optional[StateSnapshot]:
        """Load latest state for resuming conversation"""

        # Try Redis first (fast)
        cached = await self.redis.get(f"conv:{conversation_id}:latest")
        if cached:
            return StateSnapshot.parse_raw(cached)

        # Fallback to DB
        row = await self.db.fetchrow(
            """
            SELECT snapshot_data FROM conversation_snapshots
            WHERE conversation_id = $1
            ORDER BY created_at DESC LIMIT 1
            """,
            conversation_id
        )

        if row:
            snapshot = StateSnapshot.parse_raw(row['snapshot_data'])
            # Cache for next time
            await self.redis.setex(
                f"conv:{conversation_id}:latest",
                3600,
                snapshot.model_dump_json()
            )
            return snapshot

        return None

    async def load_all(self, conversation_id: UUID) -> list[StateSnapshot]:
        """Load full conversation history (for debugging/analytics)"""

        rows = await self.db.fetch(
            """
            SELECT snapshot_data FROM conversation_snapshots
            WHERE conversation_id = $1
            ORDER BY created_at ASC
            """,
            conversation_id
        )

        return [StateSnapshot.parse_raw(row['snapshot_data']) for row in rows]
```

### Interrupt/Resume Pattern

**Consult triggers interruption:**
```python
async def consult_agent(
    target_agent_id: UUID,
    question: str,
    current_conversation_id: UUID
):
    """Consult another agent - this INTERRUPTS execution"""

    # Create internal consultation message
    await create_internal_message(
        conversation_id=current_conversation_id,
        content=question,
        tagged_entity_id=target_agent_id,
        is_internal_note=True
    )

    # Invoke consulting agent asynchronously
    await invoke_consulting_agent_async(
        agent_id=target_agent_id,
        question=question,
        reply_to_conversation=current_conversation_id
    )

    # Raise exception to interrupt execution
    raise ConsultRequiredException(target_agent_id, question)
    # Execution pauses here! Will resume when consulting agent responds
```

**Consult response triggers resume:**
```python
async def handle_consult_response(
    conversation_id: UUID,
    consulting_agent_id: UUID,
    answer: str,
    persistence: ConversationStatePersistence
):
    """Handle response from consulting agent - RESUMES conversation"""

    # Load interrupted state
    snapshot = await persistence.load_latest(conversation_id)
    state = snapshot.state

    # Add consultation response to context
    state.messages.append(Message(
        sender_type='agent',
        sender_id=consulting_agent_id,
        content=answer,
        is_internal_note=True
    ))

    # Clear interruption
    state.is_interrupted = False
    state.awaiting_response_from = None

    # Save and resume
    await persistence.save(StateSnapshot(
        state=state,
        timestamp=datetime.now(),
        snapshot_id=uuid4()
    ))

    await resume_conversation(conversation_id, persistence)
```

### Redis Key Naming Convention

```
# Conversations
conv:{conversation_id}:latest             → StateSnapshot (latest, 1hr TTL)

# Temporary locks
handoff_lock:{conversation_id}            → Handoff in progress (30s TTL)
consult_lock:{conversation_id}            → Consult pending (5min TTL)

# Business quotas
tokens:{business_id}:{YYYY-MM}            → Token counter (3mo TTL)
quota:{business_id}:{YYYY-MM}             → Quota state (5min TTL)

# Rate limiting
ratelimit:{business_id}:{endpoint}        → Rate limit counter (1min TTL)
```

### Database Schema for State

```sql
-- State snapshots (Pydantic AI pattern)
CREATE TABLE conversation_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    snapshot_data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    INDEX idx_snapshots_conversation (conversation_id, created_at DESC)
);

-- Conversations table (current state only)
ALTER TABLE conversations ADD COLUMN is_interrupted BOOLEAN DEFAULT false;
ALTER TABLE conversations ADD COLUMN interrupted_reason VARCHAR(100);
ALTER TABLE conversations ADD COLUMN awaiting_response_from UUID;
```

### State Management Service

```python
# state/manager.py

class StateManager:
    """Centralized state management for conversations"""

    def __init__(self, redis_client, db_pool):
        self.persistence = ConversationStatePersistence(db_pool, redis_client)
        self.redis = redis_client
        self.db = db_pool

    async def update_handler(
        self,
        conversation_id: UUID,
        handler_type: str,
        handler_id: UUID
    ):
        """Update who's handling the conversation (key state change!)"""

        # Update DB (persistent)
        await self.db.execute(
            "UPDATE conversations SET "
            "current_handler_type = $1, current_handler_id = $2 "
            "WHERE id = $3",
            handler_type, handler_id, conversation_id
        )

        # Update cached state
        snapshot = await self.persistence.load_latest(conversation_id)
        if snapshot:
            snapshot.state.current_handler_type = handler_type
            snapshot.state.current_handler_id = handler_id
            await self.persistence.save(snapshot)

    async def start_handoff(
        self,
        conversation_id: UUID,
        from_id: UUID,
        to_id: UUID
    ):
        """Lock conversation during handoff (prevent race conditions)"""

        lock_key = f"handoff_lock:{conversation_id}"
        acquired = await self.redis.set(
            lock_key,
            json.dumps({"from": str(from_id), "to": str(to_id)}),
            nx=True,  # Only if doesn't exist
            ex=30     # 30 second TTL
        )

        if not acquired:
            raise ValueError("Handoff already in progress")

    async def check_quota(
        self,
        business_id: UUID,
        tokens_needed: int
    ) -> bool:
        """Check if business has tokens remaining"""

        current_month = datetime.now().strftime("%Y-%m")
        counter_key = f"tokens:{business_id}:{current_month}"

        used = await self.redis.get(counter_key)
        tokens_used = int(used) if used else 0

        # Get business plan limits
        plan = await self._get_business_plan(business_id)

        return tokens_used + tokens_needed <= plan.included_tokens

    async def increment_tokens(
        self,
        business_id: UUID,
        tokens_used: int
    ):
        """Track token usage for billing"""

        current_month = datetime.now().strftime("%Y-%m")
        counter_key = f"tokens:{business_id}:{current_month}"

        # Increment Redis counter
        new_total = await self.redis.incrby(counter_key, tokens_used)

        # Set expiry (3 months)
        await self.redis.expire(counter_key, 60 * 60 * 24 * 90)

        # Sync to DB every 100 tokens
        if new_total % 100 < tokens_used:
            await self._sync_token_usage_to_db(business_id, current_month, new_total)
```

### Execution with State Management

```python
# agents/executor.py

async def execute_conversation_turn(
    conversation_id: UUID,
    customer_message: str,
    state_mgr: StateManager
):
    """Execute one turn with state persistence"""

    # 1. Load or create state
    snapshot = await state_mgr.persistence.load_latest(conversation_id)

    if snapshot:
        state = snapshot.state  # Resume
    else:
        state = await initialize_new_conversation(conversation_id)  # New

    # 2. Check if interrupted
    if state.is_interrupted:
        if state.interrupted_reason == 'awaiting_consult':
            # Still waiting for consult
            return "Awaiting consultation response"

    # 3. Add customer message
    state.messages.append(Message(
        sender_type='customer',
        content=customer_message
    ))

    # 4. Execute handler
    try:
        result = await execute_agent(
            agent_id=state.current_handler_id,
            message=customer_message,
            context=state.messages[-10:]  # Last 10 messages
        )

        # Add response
        state.messages.append(Message(
            sender_type='agent',
            sender_id=state.current_handler_id,
            content=result.response,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens
        ))

    except ConsultRequiredException as e:
        # Agent needs consult - INTERRUPT
        state.is_interrupted = True
        state.interrupted_reason = 'awaiting_consult'
        state.awaiting_response_from = e.consulting_agent_id

    # 5. Save snapshot
    await state_mgr.persistence.save(StateSnapshot(
        state=state,
        timestamp=datetime.now(),
        snapshot_id=uuid4()
    ))

    return result
```

### Benefits

**1. Pause/Resume Built-in**
- Consult → Pause → Wait → Resume
- Handoff → Pause → Transfer → Resume
- Human escalation → Pause → Wait → Resume

**2. Full History for Debugging**
- See exact state at each turn
- Replay conversations
- Debug why agent made a decision

**3. Distributed Execution Ready**
- State in DB, not memory
- Conversations can pause on server A, resume on server B
- Perfect for scaling

**4. Aligns with Industry Patterns**
- Follows Pydantic AI's proven state persistence model
- Similar to workflow engines (Temporal, Airflow)

## Pricing Model

### Hybrid Token + Agent-Based Pricing

**Starter: $99/month**
- 2 active agents
- 50K tokens/month included
- $0.003/1K tokens overage
- 1 channel per agent

**Professional: $299/month**
- 5 active agents
- 500K tokens/month included
- $0.0025/1K tokens overage (volume discount)
- 3 channels per agent
- Advanced analytics

**Enterprise: Custom**
- Unlimited agents
- Custom token allowance
- Volume discounts
- Dedicated support
- Custom tools/integrations

### Pricing Rationale
- **Per-agent limits** prevent runaway costs
- **Token-based** aligns cost with actual usage (fair)
- **Included tokens** makes pricing predictable
- **Overage charges** ensures profitability on heavy users

## Technology Stack

- **Framework**: FastAPI (async Python)
- **AI**: Pydantic AI (Anthropic Claude)
- **Database**: PostgreSQL with asyncpg
- **Messaging**: WhatsApp Business API, Telegram Bot API
- **Payments**: Stripe (future: Paystack for African markets)
- **Shipping**: Partner APIs (DHL, FedEx, local carriers)

## File Structure

### Current Structure
```
autobiz/
├── api/
│   ├── main.py
│   └── routes/
│       ├── webhooks.py            # Channel webhooks (WhatsApp, Telegram)
│       ├── businesses.py          # Business dashboard
│       └── admin.py               # Subscription management
├── agents/
│   ├── base.py                    # ✅ Base agent config
│   ├── deps.py                    # ✅ AgentDeps (business_id, etc.)
│   ├── customer_agent.py          # ✅ Current single agent
│   └── tools/                     # ✅ Existing tools
│       ├── products.py            #    - product_search, product_check_inventory
│       ├── customers.py           #    - customer_lookup
│       ├── conversations.py       #    - conversation tools
│       └── __init__.py
├── db/
│   ├── connection.py              # ✅ PostgreSQL with asyncpg
│   ├── queries/                   # ✅ Query functions
│   │   ├── __init__.py
│   │   ├── agent.py               #    - Agent DB operations
│   │   ├── customer.py            #    - Customer queries
│   │   └── product.py             #    - Product queries
│   ├── models/                    # ✅ Pydantic models
│   │   ├── agent.py               #    - Agent model
│   │   ├── customer.py
│   │   ├── product.py
│   │   └── ...
│   └── schema/                    # ✅ SQL migrations
│       ├── 000_init.sql
│       ├── 001_create_users.sql
│       ├── 002_create_subscription_plans.sql
│       ├── 003_create_businesses.sql
│       ├── 004_create_agent.sql   # ⚠️  Single agent per business
│       ├── 005_create_customer.sql
│       ├── 006_create_conversation.sql
│       ├── 007_create_message.sql
│       ├── 008_create_product.sql
│       └── run_migrations.py
├── schemas/                       # ✅ API schemas
├── config/
│   └── settings.py                # ✅ Environment config
└── tests/                         # ✅ Tests
    └── db/
        └── queries/
            └── test_agent.py
```

### Target Structure (Multi-Agent System)
```
autobiz/
├── api/
│   ├── main.py
│   └── routes/
│       ├── webhooks.py
│       ├── businesses.py
│       ├── admin.py
│       └── agents.py              # 🔲 NEW: Agent CRUD endpoints
├── agents/
│   ├── base.py
│   ├── deps.py
│   ├── executor.py                # 🔲 NEW: Multi-agent execution logic
│   ├── customer_agent.py          # ⚠️  To be deprecated/migrated
│   └── tools/
│       ├── ecommerce/             # 🔲 NEW: Reorganized by category
│       │   ├── __init__.py
│       │   ├── product_search.py  #    (migrated from tools/products.py)
│       │   ├── inventory_check.py
│       │   ├── order_lookup.py    # 🔲 NEW
│       │   └── shipping.py        # 🔲 NEW
│       ├── service/               # 🔲 NEW: Service business tools
│       │   ├── __init__.py
│       │   ├── appointment_booking.py
│       │   ├── case_creation.py
│       │   └── document_upload.py
│       ├── universal/             # 🔲 NEW: Cross-agent tools
│       │   ├── __init__.py
│       │   ├── customer_lookup.py #    (migrated from tools/customers.py)
│       │   ├── send_message.py    # 🔲 NEW
│       │   ├── create_ticket.py   # 🔲 NEW
│       │   └── conversation_history.py
│       ├── payment/               # 🔲 NEW: Payment tools
│       │   ├── payment_request.py
│       │   └── payment_status.py
│       └── registry.py            # 🔲 NEW: Tool registration system
├── db/
│   ├── connection.py
│   ├── queries/
│   │   ├── __init__.py
│   │   ├── agent.py               # ⚠️  Update for multi-agent
│   │   ├── customer.py
│   │   ├── product.py
│   │   └── token_usage.py         # 🔲 NEW: Billing queries
│   ├── models/
│   │   ├── agent.py               # ⚠️  Update for multi-agent
│   │   ├── tool_registry.py       # 🔲 NEW
│   │   ├── token_usage.py         # 🔲 NEW
│   │   └── ...
│   └── schema/
│       ├── 000-008_*.sql          # ✅ Existing schemas
│       ├── 009_migrate_agent_to_multi.sql        # 🔲 NEW: Multi-agent migration
│       ├── 010_create_tool_registry.sql          # 🔲 NEW
│       ├── 011_update_conversations.sql          # 🔲 NEW: Handler + interruption
│       ├── 012_update_messages.sql               # 🔲 NEW: Tagging + tokens
│       ├── 013_create_token_usage.sql            # 🔲 NEW
│       ├── 014_create_escalation_history.sql     # 🔲 NEW
│       ├── 015_create_handoff_history.sql        # 🔲 NEW
│       ├── 016_create_conversation_snapshots.sql # 🔲 NEW: State persistence
│       └── run_migrations.py
├── state/                         # 🔲 NEW: State management
│   ├── __init__.py
│   ├── models.py                  #    ConversationState, StateSnapshot
│   ├── persistence.py             #    ConversationStatePersistence
│   ├── manager.py                 #    StateManager
│   └── redis_client.py            #    Redis connection setup
├── schemas/
├── config/
│   ├── settings.py
│   └── redis.py                   # 🔲 NEW: Redis configuration
└── tests/

Legend:
✅ Exists (current implementation)
⚠️  Needs modification
🔲 Needs creation
```

## Migration Path

### Phase 1: State Management Foundation
1. Create `conversation_snapshots` table (state persistence)
2. Add `is_interrupted`, `interrupted_reason` to `conversations`
3. Implement `ConversationStatePersistence` class
4. Setup Redis for caching (optional for MVP, can use PostgreSQL only)
5. Build `StateManager` with pause/resume support

### Phase 2: Multi-Agent Foundation
1. Remove UNIQUE constraint on `agent.business_id`
2. Add `agent_type`, `description`, `config` JSONB to `agents`
3. Create `tool_registry` table
4. Update `conversations` with `current_handler_type`, `current_handler_id`
5. Migrate existing single agent to new schema

### Phase 3: Collaboration System
1. Update `messages` with universal tagging (`tagged_entity_type`, `tagged_entity_id`)
2. Create `handoff_history` table
3. Create `escalation_history` table
4. Implement `handoff_to_agent` tool with validation
5. Implement `consult_agent` tool with interrupt/resume
6. Build handoff vs consult validation logic

### Phase 4: Tool System
1. Refactor existing tools into registry pattern
2. Implement dynamic tool loading
3. Create tool categories (ecommerce, service, universal, collaboration)
4. Build collaboration tools (handoff, consult, notify)
5. Tool discovery/documentation

### Phase 5: Token Tracking & Billing
1. Implement token usage tracking in state
2. Create `token_usage` table for billing
3. Build quota checking (Redis counters)
4. Implement overage calculations
5. Usage analytics dashboard

### Phase 6: Advanced Features
1. Agent templates (pre-built configs)
2. Agent configuration UI
3. Multi-language support
4. Custom tool builder
5. A/B testing for agents
6. Performance analytics

## Tool Migration Strategy

### Converting Existing Tools to Registry Pattern

**Current** (tied to `customer_agent`):
```python
# agents/tools/products.py
from agents.customer_agent import customer_agent

@customer_agent.tool
async def product_search(ctx: RunContext[AgentDeps], query: str, limit: int = 5):
    products = await search_products(ctx.deps.business_id, query, limit)
    return format_results(products)
```

**Target** (agent-agnostic, registerable):
```python
# agents/tools/ecommerce/product_search.py
from pydantic import BaseModel
from db.queries.product import search_products

class ProductSearchTool:
    name = "product_search"
    category = "ecommerce"
    description = "Search for products in business catalog"
    required_tables = ["products"]

    class Parameters(BaseModel):
        query: str
        limit: int = 10

    @staticmethod
    async def execute(business_id: str, query: str, limit: int = 10):
        """Execute product search - called by any agent"""
        products = await search_products(business_id, query, limit)
        return format_results(products)

# Register in agents/tools/registry.py
from agents.tools.ecommerce.product_search import ProductSearchTool
ToolRegistry.register(ProductSearchTool)
```

### Migration Checklist

**Existing tools to migrate:**
- ✅ `product_search` ([agents/tools/products.py](agents/tools/products.py)) → `agents/tools/ecommerce/product_search.py`
- ✅ `product_check_inventory` ([agents/tools/products.py](agents/tools/products.py)) → `agents/tools/ecommerce/inventory_check.py`
- ✅ `customer_lookup` ([agents/tools/customers.py](agents/tools/customers.py)) → `agents/tools/universal/customer_lookup.py`
- ✅ Conversation tools ([agents/tools/conversations.py](agents/tools/conversations.py)) → `agents/tools/universal/conversation_history.py`

**New tools to create:**
- 🔲 `order_lookup`, `order_create` (ecommerce)
- 🔲 `send_message`, `create_ticket` (universal)
- 🔲 `payment_request`, `payment_status` (payment)
- 🔲 Service-based tools (appointment_booking, case_creation, etc.)

### Benefits of Tool Registry

1. **Agent independence**: Tools work with any agent, not tied to `customer_agent`
2. **Dynamic loading**: Agents only load tools they need
3. **Easy discovery**: `ToolRegistry.get_tools_by_category("ecommerce")`
4. **Metadata tracking**: Store tool info in database for UI/docs
5. **Testability**: Test tools independently of agents
6. **Extensibility**: Easy to add custom business-specific tools

## Design Principles

1. **Flexibility over assumptions**: Support both e-commerce and service-based businesses
2. **Tool composability**: Mix and match tools per agent
3. **Per-business agents**: No multi-tenant agents (custom rules per business)
4. **Token transparency**: Clear tracking and billing
5. **Graceful escalation**: Easy handoff to humans when needed
6. **Developer-friendly**: Easy to add new tools and agent types
7. **Keep existing data**: CRM tables (businesses, customers, products) stay intact
