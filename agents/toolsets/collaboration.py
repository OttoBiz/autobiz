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
    target_agent_key: str,
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
        target_agent_key: Key of the agent to consult (e.g., "inventory", "legal", "pricing")
        question: Specific question to ask (be clear and concise)

    Returns:
        Answer from the consulted agent

    Important:
    - conversation.current_handler_id UNCHANGED (you stay in control)
    - Creates internal message (is_internal_note=true)
    - Consultation happens behind the scenes
    - You receive answer and continue with customer
    """
    # Get current agent info for validation
    current_agent_key = ctx.deps.current_agent_key

    # TODO: Add safeguards from COLLABORATION.md
    # - Check target agent exists
    # - Check allowlist (can_consult)
    # - Check loop detection
    # - Track consultation in agent_collaborations table

    # Build consultation context for the target agent
    # Following Anthropic's pattern: clear task boundaries, explicit context
    consultation_message = f"""[INTERNAL CONSULTATION from {current_agent_key}]

You are being consulted by the {current_agent_key} agent.
Please answer this specific question and return your findings.

QUESTION:
{question}

Provide a clear, concise answer. The requesting agent will use your response to continue their customer conversation.
"""

    # Reuse executor to spawn the target agent (Anthropic orchestrator-worker pattern)
    # The target agent is loaded with its own:
    # - system_prompt and personality
    # - tool_groups (different tools than the orchestrator)
    # - No collaboration tools (subagents can't spawn more agents)
    answer = await ctx.deps.executor.run(
        business_id=ctx.deps.business_id,
        conversation_id=ctx.deps.conversation_id,
        agent_key=target_agent_key,
        user_message=consultation_message,
        deps=ctx.deps,
        message_history=[],  # Fresh context - just the question, no conversation history
    )

    return answer
