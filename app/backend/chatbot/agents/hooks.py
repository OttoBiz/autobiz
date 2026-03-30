"""Hook utilities for PydanticAI agents."""

import logfire

from backend.chatbot.agents.outbound import OutboundDeps

logfire.configure()


async def notify_main_agent(outbound_deps: OutboundDeps) -> None:
    """Called after the outbound agent's mark_completed tool fires.

    Triggers a system-initiated main agent run so it can craft a proactive
    message to the customer based on the vendor resolution.
    """
    from backend.chatbot.agents.main_agent import AgentDeps, agent
    from backend.db.cache_utils import get_user_state

    resolution = outbound_deps.resolution
    if not resolution:
        logfire.warn(
            "notify_main_agent: resolution is empty",
            task_key=outbound_deps.task_key,
        )
        return

    user_state = (
        await get_user_state(outbound_deps.customer_id, outbound_deps.business_id)
        or {}
    )
    chat_history = user_state.get("chat_history", [])

    deps = AgentDeps(
        user_id=outbound_deps.customer_id,
        business_id=outbound_deps.business_id,
        chat_history=chat_history,
        state=user_state,
    )

    system_prompt = (
        f"[System] Outbound task '{outbound_deps.task_key}' resolved.\n"
        f"Result: {resolution.get('result', '')}\n"
        f"Vendor note: {resolution.get('vendor_note', '')}\n\n"
        "Craft a proactive message to the customer based on the current "
        "conversation state. Be concise and helpful."
    )

    result = await agent.run(system_prompt, deps=deps)

    logfire.info(
        "main_agent produced proactive response",
        customer_id=outbound_deps.customer_id,
        task_key=outbound_deps.task_key,
        response=result.output,
    )

    # TODO: send result.output to customer via WhatsApp proactive push
    # TODO: append system event + response to chat_history
    # TODO: mark outbound task status as "delivered" in shared state
