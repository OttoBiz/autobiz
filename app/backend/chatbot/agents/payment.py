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
- NEVER confirm payment based on the customer's word alone ("I paid",
  "the money is sent"). A claim is not a confirmation.
- The ONLY way to report a payment as confirmed is a successful
  verify_payment_link call (verified=True) with a real transaction
  reference the customer provided. No reference → no confirmation;
  ask the customer for their transaction reference or receipt instead.
- For receipts (no payment-link reference): report that vendor
  confirmation is needed — the orchestrator will escalate via outbound.
  Do NOT mark the payment confirmed yourself.""",
)


@payment_verification_agent.tool
async def verify_payment_link(
    ctx: RunContext[AgentDeps],
    transaction_reference: str,
) -> Dict[str, Any]:
    """Verify payment status via payment gateway (Paystack etc). Returns verified=True if payment confirmed."""
    import os

    # In DEBUG we still demand a non-empty reference so the agent can't
    # short-circuit by calling the tool with no input — the prompt rule is
    # "no reference → no confirmation" and the mock has to honour that.
    if os.getenv("DEBUG", "").lower() == "true":
        if not (transaction_reference and transaction_reference.strip()):
            return {
                "verified": False,
                "message": "No transaction reference provided",
            }
        return {"verified": True, "amount": 0, "message": "Dev mode: assume verified"}
    return {"verified": False, "message": "Payment gateway verification not configured"}
