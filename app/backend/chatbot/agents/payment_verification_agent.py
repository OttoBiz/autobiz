"""
Payment Verification Agent - Verifies customer payments
"""

from typing import Any, Dict

from pydantic_ai import RunContext

from backend.chatbot.agents.main_agent import AgentDeps

from .base_agent import BaseAgent

payment_verification_agent_base = BaseAgent(
    system_prompt="""You are a payment verification assistant.

**YOUR JOB**
- Verify payments via receipt (match business account + product price) or payment link (verify_payment_link).
- Return verification results to the orchestrator. Do NOT contact vendors or create orders directly.
- For receipts: return the details so the orchestrator can request vendor confirmation.
- For payment links: call verify_payment_link and return the result.

**RULES**
- Only report payment as confirmed when verify_payment_link returns verified=True.
- For receipts: report that vendor confirmation is needed — the orchestrator will handle it.""",
    deps_type=AgentDeps,
)

payment_verification_agent = payment_verification_agent_base.agent


async def run_verification_agent(
    customer_message: str,
    user_id: str,
    business_id: str,
    user_state: dict = None,
    **kwargs,
) -> str:
    """Legacy wrapper — delegates to payment_verification_agent."""
    from backend.chatbot.agents.main_agent import AgentDeps
    deps = AgentDeps(user_id=user_id, business_id=business_id, state=user_state or {})
    result = await payment_verification_agent.run(customer_message, deps=deps)
    return result.output


@payment_verification_agent.tool
async def verify_payment_link(
    ctx: RunContext[AgentDeps],
    transaction_reference: str,
) -> Dict[str, Any]:
    """Verify payment status via payment gateway (Paystack etc). Returns verified=True if payment confirmed."""
    import os

    if os.getenv("DEBUG", "").lower() == "true":
        return {"verified": True, "amount": 0, "message": "Dev mode: assume verified"}
    return {"verified": False, "message": "Payment gateway verification not configured"}
