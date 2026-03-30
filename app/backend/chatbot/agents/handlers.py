import asyncio
import uuid
from typing import Any

from backend.chatbot.agents.customer_complaint_agent import customer_complaint_agent
from backend.chatbot.agents.logistics_agent import logistics_agent
from backend.chatbot.agents.main_agent import AgentDeps
from backend.chatbot.agents.outbound import OutboundDeps, outbound_agent
from backend.chatbot.agents.payment_verification_agent import payment_verification_agent
from backend.chatbot.agents.product_agent import product_agent
from backend.db.db_utils import get_business_info


async def handle_product(deps: AgentDeps, prompt: str) -> dict[str, Any]:
    result = await product_agent.run(prompt, deps=deps)
    return {"response": result.output}


async def handle_payment(deps: AgentDeps, prompt: str) -> dict[str, Any]:
    result = await payment_verification_agent.run(prompt, deps=deps)
    return {"response": result.output}


async def handle_logistics(deps: AgentDeps, prompt: str) -> dict[str, Any]:
    result = await logistics_agent.run(prompt, deps=deps)
    return {"response": result.output}


async def handle_customer_relation(deps: AgentDeps, prompt: str) -> dict[str, Any]:
    result = await customer_complaint_agent.run(prompt, deps=deps)
    return {"response": result.output}


async def _run_outbound(prompt: str, outbound_deps: OutboundDeps) -> None:
    """Run outbound agent in background.

    On completion the after_tool_execute hook on mark_completed fires
    notify_main_agent, which triggers a system-initiated main agent run.
    """
    await outbound_agent.run(prompt, deps=outbound_deps)


async def handle_outbound(deps: AgentDeps, prompt: str) -> dict[str, Any]:
    task_key = f"out-{uuid.uuid4().hex[:8]}"
    business_info = await get_business_info(deps.business_id)
    business_name = business_info.get("name", "") if business_info else ""

    outbound_deps = OutboundDeps(
        task_key=task_key,
        customer_id=deps.user_id,
        business_id=deps.business_id,
        business_name=business_name,
    )

    deps.outbound.append(outbound_deps)

    # Fire and forget
    asyncio.create_task(_run_outbound(prompt, outbound_deps))

    return {"status": "pending", "task_key": task_key}
