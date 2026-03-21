"""
Payment Verification Agent - Verifies customer payments
"""

from typing import Any, Dict, Optional

from pydantic_ai import RunContext

from backend.chatbot.agents.central_agent import run_central_agent
from backend.chatbot.agents.central_agent_utils import create_structured_input
from backend.chatbot.agents.main_agent import AgentDeps
from backend.struct import Customer, Vendor

from .base_agent import BaseAgent


payment_verification_agent_base = BaseAgent(
    system_prompt="""You are a payment verification assistant.

**YOUR JOB**
- Verify payments via receipt (match business account + product price) or payment link (verify_payment_link).
- On confirmation: notify central agent to create order.
- For receipts: notify vendor for verbal confirmation first; when vendor confirms, call notify_central_payment_confirmed.
- For payment links: call verify_payment_link; if success, call notify_central_payment_confirmed.

**RULES**
- Only notify_central_payment_confirmed when payment is definitively confirmed.
- For receipts: vendor must confirm before calling notify_central_payment_confirmed.""",
    deps_type=AgentDeps,
)

payment_verification_agent = payment_verification_agent_base.agent


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


@payment_verification_agent.tool
async def notify_central_payment_confirmed(
    ctx: RunContext[AgentDeps],
    product_name: str,
    amount: float,
    quantity: int = 1,
    delivery_address: Optional[str] = None,
) -> Dict[str, Any]:
    """Notify central agent that payment is confirmed. Central agent will create order in DB."""
    agent_input = await create_structured_input(
        sender="Agent",
        recipient="Agent",
        message=f"Payment confirmed. Create order: product={product_name}, quantity={quantity}, amount=${amount}. "
        f"Delivery address: {delivery_address or 'To be collected'}",
        customer=Customer(id=ctx.deps.user_id),
        business=Vendor(id=ctx.deps.business_id),
    )
    try:
        await run_central_agent(event_message=agent_input, user_state=ctx.deps.state)
        return {"status": "sent", "message": "Central agent notified. Order will be created."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@payment_verification_agent.tool
async def notify_vendor_for_confirmation(
    ctx: RunContext[AgentDeps],
    product_name: str,
    amount: float,
    transaction_reference: Optional[Dict[Any, str]] = None,
    receipt_details: Optional[str] = None,
) -> Dict[str, Any]:
    """Notify vendor to confirm payment was received."""
    agent_input = await create_structured_input(
        sender="Agent",
        recipient="Vendor",
        message=f"Payment verification request: Customer claims payment for '{product_name}', Amount: ${amount}. Receipt: {receipt_details}, Ref: {transaction_reference}. Please confirm.",
        customer=Customer(id=ctx.deps.user_id),
        business=Vendor(id=ctx.deps.business_id),
    )
    try:
        await run_central_agent(event_message=agent_input, user_state=ctx.deps.state)
    except Exception as e:
        return {"status": "error", "message": f"Error notifying vendor: {e}"}

    return {"status": "vendor_notified", "message": "Vendor notified. Awaiting confirmation."}
