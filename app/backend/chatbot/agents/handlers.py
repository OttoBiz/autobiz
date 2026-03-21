from typing import Any

from backend.chatbot.agents.main_agent import AgentDeps
from backend.chatbot.agents.product_agent import product_agent
from backend.chatbot.agents.payment_verification_agent import payment_verification_agent
from backend.chatbot.agents.logistics_agent import logistics_agent
from backend.chatbot.agents.customer_complaint_agent import customer_complaint_agent


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
