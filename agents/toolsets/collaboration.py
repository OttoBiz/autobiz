"""Agent collaboration toolset for consultation operations.

All tools are prefixed with 'collab_' to prevent naming collisions.

Pattern:
- CONSULT (tool): Simple GET - returns info to calling agent
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
