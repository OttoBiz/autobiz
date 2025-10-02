"""Conversation management tools for the AI agent."""

from uuid import UUID

from pydantic_ai import RunContext

from agents.customer_agent import customer_agent
from agents.deps import AgentDeps
from db.queries import create_message, escalate_conversation


@customer_agent.tool
async def conversation_escalate(
    ctx: RunContext[AgentDeps],
    reason: str,
    user_id: str,
) -> str:
    """
    Escalate the current conversation to a human team member.

    Use this tool when:
    - Customer issue is too complex for you to handle
    - Customer explicitly requests to speak with a human
    - You need human judgment for refunds, complaints, or policy exceptions
    - Technical issues beyond your capabilities arise

    Do NOT use if:
    - Issue can be resolved with available tools
    - Customer question is straightforward
    - You haven't attempted to help first

    Args:
        reason: Clear explanation of why escalation is needed (will be shown to the human agent)
        user_id: ID of the team member to assign (UUID format)

    Returns:
        Confirmation message to inform the customer that a human will take over.

    Important:
    - Conversation status changes to 'escalated'
    - Human agent receives the escalation reason
    - Customer should be informed politely that a human will assist
    - Original conversation context is preserved
    """
    if not ctx.deps.conversation_id:
        return "Error: Cannot escalate - no active conversation found."

    if not reason or len(reason.strip()) < 10:
        return "Error: Please provide a detailed reason for escalation (at least 10 characters)."

    try:
        user_uuid = UUID(user_id)
    except ValueError:
        return f"Error: Invalid user_id format. Must be a valid UUID, got: {user_id}"

    # Escalate the conversation
    conversation = await escalate_conversation(ctx.deps.conversation_id, user_uuid)

    if not conversation:
        return "Error: Failed to escalate conversation. The conversation may no longer exist."

    # Create an internal note with the escalation reason
    await create_message(
        conversation_id=ctx.deps.conversation_id,
        sender_type="agent",
        content=f"[ESCALATION] Reason: {reason}",
        is_internal=True,
    )

    return f"""Conversation successfully escalated to human support.

Internal note: {reason}

Please inform the customer:
"I've connected you with one of our team members who will be able to better assist you with this. They'll be with you shortly and will have full context of our conversation."
"""


@customer_agent.tool
async def conversation_add_note(
    ctx: RunContext[AgentDeps],
    note: str,
) -> str:
    """
    Add an internal note to the conversation that is NOT visible to the customer.

    Use this tool when:
    - You need to document important context for human agents
    - Customer mentions something that needs follow-up
    - You notice patterns or issues worth noting
    - Recording observations about customer sentiment or behavior

    Do NOT use for:
    - Information that should be visible to the customer
    - General conversation messages (those are logged automatically)
    - Customer-facing responses

    Args:
        note: Internal note content (will only be visible to business team members)

    Returns:
        Confirmation that the note was added.

    Important:
    - Note is marked as internal (is_internal=true)
    - Customer cannot see this note
    - Visible to all team members viewing the conversation
    - Use for context that helps humans provide better service
    """
    if not ctx.deps.conversation_id:
        return "Error: Cannot add note - no active conversation found."

    if not note or len(note.strip()) < 5:
        return "Error: Please provide a meaningful note (at least 5 characters)."

    await create_message(
        conversation_id=ctx.deps.conversation_id,
        sender_type="agent",
        content=f"[INTERNAL NOTE] {note.strip()}",
        is_internal=True,
    )

    return f"✅ Internal note added successfully. This information is now visible to your team but not to the customer."
