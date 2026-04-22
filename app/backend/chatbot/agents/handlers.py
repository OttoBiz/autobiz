from typing import Any
from uuid import UUID

from backend.chatbot.agents.customer_complaint_agent import customer_complaint_agent
from backend.chatbot.agents.logistics_agent import logistics_agent
from backend.chatbot.agents.main_agent import AgentDeps
from backend.chatbot.agents.outbound import dispatch
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


async def handle_outbound(
    deps: AgentDeps, prompt: str, *, party: str = "vendor"
) -> dict[str, Any]:
    # TODO(batch-5b): this file is deleted in 5b; central calls dispatch() directly.
    business_info = await get_business_info(deps.business_id)
    business_name = business_info.get("name", "") if business_info else None
    task_key = await dispatch(
        business_id=UUID(deps.business_id),
        customer_id=UUID(deps.user_id),
        party=party,
        initiated_by="customer",
        dispatch_prompt=prompt,
        business_name=business_name,
    )
    return {"status": "pending", "task_key": task_key}
