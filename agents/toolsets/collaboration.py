"""Agent collaboration toolset for handoff and consult operations.

All tools are prefixed with 'collab_' to prevent naming collisions.

Mental Model (from ARCHITECTURE.md):
- CONSULT = Simple GET (read operations, no customer interaction)
- HANDOFF = WRITE + Complex GET (write ops or multi-turn customer interactions)
"""

from pydantic_ai import FunctionToolset, RunContext

from agents.deps import AgentDeps

# Create toolset
collaboration_toolset = FunctionToolset()


@collaboration_toolset.tool
async def consult(
    ctx: RunContext[AgentDeps],
    target_agent_role: str,
    question: str,
) -> str:
    """Ask another agent a quick question (Simple GET operation).

    Operation: READ (Internal consultation, no state change)
    Customer Interaction: No (customer doesn't see this)

    Mental Model: CONSULT = Simple GET

    Use this tool when:
    - You need specific information the other agent has
    - It's a one-shot question/answer exchange
    - You'll continue handling the conversation after getting the answer
    - Customer doesn't need to interact with the other agent

    Examples (Simple GET):
    - "What's inventory count for SKU-123?" → Data lookup
    - "What's our return policy for electronics?" → Policy lookup
    - "Can we offer net-30 terms to customer ID xyz?" → Approval/rule check
    - "What's shipping cost to ZIP 12345?" → Calculation
    - "What's lead time for custom orders?" → Information retrieval

    Do NOT use for:
    - WRITE operations (use handoff instead)
    - Complex questions requiring multiple exchanges (use handoff)
    - Cases where customer needs to interact with specialist (use handoff)

    Args:
        target_agent_role: Role of the agent to consult (e.g., "inventory", "legal", "pricing")
        question: Specific question to ask (be clear and concise)

    Returns:
        Answer from the consulted agent

    Important:
    - conversation.current_handler_id UNCHANGED (you stay in control)
    - Creates internal message (is_internal_note=true)
    - Consultation happens behind the scenes
    - You receive answer and continue with customer
    """
    # TODO: Implement consultation logic
    # 1. Validate target agent exists and consultation is allowed
    # 2. Create internal consultation request
    # 3. Invoke consulting agent asynchronously
    # 4. Wait for response (may raise ConsultRequiredException to pause execution)
    # 5. Return answer to requesting agent

    raise NotImplementedError(
        "Consult tool not yet implemented. "
        "This will be implemented in Phase 3: Collaboration System."
    )


@collaboration_toolset.tool
async def handoff(
    ctx: RunContext[AgentDeps],
    target_agent_role: str,
    reason: str,
    context: str,
) -> str:
    """Transfer conversation to another agent (WRITE or Complex GET).

    Operation: WRITE (Changes conversation handler)
    Customer Interaction: Yes (different agent takes over)

    Mental Model: HANDOFF = WRITE + Complex GET

    Use this tool when:
    - You need to CREATE/UPDATE/DELETE something (write operation)
    - Customer needs to interact with specialist for complex/multi-turn GET
    - Requires multiple exchanges outside your domain
    - Customer explicitly requested different service
    - You lack the tools or authority to continue

    Examples (WRITE operations):
    - "Process this refund" → Changes order state
    - "Create custom pricing proposal" → Creates artifact
    - "Update customer contract terms" → Modifies agreement
    - "Cancel and recreate order" → State changes

    Examples (Complex/Interactive GET):
    - "Design enterprise solution for customer" → Multi-turn with architect
    - "Which product best fits customer's specific needs?" → Interactive consultation
    - "Help customer troubleshoot technical issue" → Diagnostic dialogue
    - "Negotiate custom contract terms" → Back-and-forth discussion

    Do NOT use for:
    - Simple data lookups (use consult instead)
    - Quick yes/no questions (use consult instead)
    - Information you can get in one question (use consult instead)

    Args:
        target_agent_role: Role of the agent to hand off to (e.g., "sales", "support", "legal")
        reason: Why handoff is needed (shown to receiving agent)
        context: Information the new agent needs to know

    Returns:
        Confirmation that handoff was successful

    Important:
    - conversation.current_handler_id CHANGES to target agent
    - Original agent stops responding
    - New handler takes over completely
    - Creates handoff_history record
    - Customer-visible transition
    """
    # TODO: Implement handoff logic
    # 1. Validate handoff is allowed (target agent in can_handoff_to list)
    # 2. Create handoff_history record
    # 3. Update conversation.current_handler_id
    # 4. Send context to receiving agent
    # 5. Stop current agent execution

    raise NotImplementedError(
        "Handoff tool not yet implemented. "
        "This will be implemented in Phase 3: Collaboration System."
    )


# Golden Rule guidance
_GOLDEN_RULE = """
## Golden Rule for CONSULT vs HANDOFF

Ask yourself: "Will the OTHER agent need to talk to the customer?"

- YES → Use handoff (customer needs specialist interaction)
- NO → Use consult (just need information, you continue)

Secondary question: "Does this change system state?"

- YES (write operation) → Use handoff
- NO (read operation) → Is it simple or complex?
  - Simple GET → Use consult
  - Complex GET (multi-turn) → Use handoff
"""

# Export with prefix
collaboration_toolset = collaboration_toolset.prefix("collab_")
