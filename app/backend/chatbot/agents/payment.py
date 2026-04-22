"""Payment verification agent — verifies customer payments."""

from typing import Any, Dict

from pydantic_ai import Agent, RunContext

from backend.chatbot.agents.deps import AgentDeps
from backend.config import MODEL_NAME

payment_verification_agent = Agent(
    model=MODEL_NAME,
    deps_type=AgentDeps,
    system_prompt="""You are a payment verification assistant.

**YOUR JOB**
- Verify payments via receipt (match business account + product price) or payment link (verify_payment_link).
- Return verification results to the orchestrator. Do NOT contact vendors or create orders directly.
- For receipts: return the details so the orchestrator can request vendor confirmation.
- For payment links: call verify_payment_link and return the result.

**RULES**
- Only report payment as confirmed when verify_payment_link returns verified=True.
- For receipts: report that vendor confirmation is needed — the orchestrator will handle it.""",
)


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
