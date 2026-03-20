"""
Payment Verification Agent - Verifies customer payments
Converted to pydantic_ai with media processing support
"""

from typing import Any, Dict, Optional

from fastapi import BackgroundTasks
from pydantic import BaseModel
from pydantic_ai import RunContext

from backend.chatbot.agents.central_agent import run_central_agent
from backend.chatbot.agents.central_agent_utils import create_structured_input
from backend.struct import Customer, Vendor
from backend.chatbot.utils.agent_utils import get_or_create_user_state, save_user_state
from backend.db.db_utils import get_business_info

from .base_agent import BaseAgent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)


class PaymentVerificationDeps(BaseModel):
    """Dependencies for payment verification agent"""

    user_id: str
    business_id: str
    user_state: Optional[Dict[str, Any]] = None
    api_key: Optional[str] = None


# Initialize payment verification agent
payment_verification_agent_base = BaseAgent(
    system_prompt="""You are a payment verification assistant.

**YOUR JOB**
- Verify payments via receipt (match business account + product price) or payment link (verify_payment_link).
- On confirmation: notify central agent to create order. Central agent creates order in DB only after payment confirmed.
- For receipts: notify vendor for verbal confirmation first; when vendor confirms, call notify_central_payment_confirmed.
- For payment links: call verify_payment_link; if success, call notify_central_payment_confirmed.

**TOOLS**
- verify_payment_link: Check payment status via payment gateway. Use when customer paid via link.
- notify_vendor_for_confirmation: Ask vendor to confirm receipt payment.
- notify_central_payment_confirmed: Call when payment is confirmed (vendor said yes, or link verified). Central agent will create order.

**RULES**
- Only notify_central_payment_confirmed when payment is definitively confirmed.
- For receipts: vendor must confirm before calling notify_central_payment_confirmed.""",
    deps_type=PaymentVerificationDeps
)

payment_verification_agent = payment_verification_agent_base.agent


@payment_verification_agent.tool
async def verify_payment_link(
    ctx: RunContext[PaymentVerificationDeps],
    transaction_reference: str,
) -> Dict[str, Any]:
    """Verify payment status via payment gateway (Paystack etc). Returns verified=True if payment confirmed."""
    # TODO: Integrate with Paystack verify transaction API
    # For now, assume reference format indicates success in dev
    import os
    if os.getenv("DEBUG", "").lower() == "true":
        return {"verified": True, "amount": 0, "message": "Dev mode: assume verified"}
    return {"verified": False, "message": "Payment gateway verification not configured"}


@payment_verification_agent.tool
async def notify_central_payment_confirmed(
    ctx: RunContext[PaymentVerificationDeps],
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
        await run_central_agent(event_message=agent_input, user_state=ctx.deps.user_state)
        return {"status": "sent", "message": "Central agent notified. Order will be created."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@payment_verification_agent.tool
async def notify_vendor_for_confirmation(
    ctx: RunContext[PaymentVerificationDeps],
    product_name: str,
    amount: float,
    transaction_reference: Optional[Dict[Any, str]] = None,
    receipt_details: Optional[str] = None
) -> Dict[str, Any]:
    """Use this function to notify vendor to confirm payment verification"""
    # This will trigger central agent to send message to vendor
    agent_input = await create_structured_input(
        sender="Agent",
        recipient="Vendor",
        message=f"Payment verification request: Customer claims payment for product '{product_name}', Amount: ${amount}. Receipt details: {receipt_details}, Transaction reference: {transaction_reference}. Please confirm if payment was received.",
        customer=Customer(id=ctx.deps.user_id),
        business=Vendor(id=ctx.deps.business_id),
    )
    
    try:
        await run_central_agent(
            event_message = agent_input,
                user_state=  ctx.deps.user_state,
            )
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error notifying vendor: {e}"
        }
    
    return {
        "status": "vendor_notified",
        "message": "Vendor notified. When vendor confirms payment, call notify_central_payment_confirmed to create order.",
    }


async def run_verification_agent(
    customer_message: str,
    user_id: str,
    business_id: str,
    product_name: Optional[str] = None,
    user_state: Optional[Dict[str, Any]] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    receipt_data: Optional[str] = None,
    debug: bool = False,
    **kwargs,
) -> str:
    """
    Run payment verification agent with dynamic business and product details.

    Args:
        customer_message: Customer message with payment details
        user_id: User ID
        business_id: Business ID
        product_name: Product being verified (from routing agent or chat history)
        user_state: Optional user state
        background_tasks: Background tasks
        receipt_data: Extracted receipt data from file processing
        debug: Debug mode

    Returns:
        Verification response message
    """
    if not user_state:
        user_state = await get_or_create_user_state(user_id, business_id)

    business_info = user_state.get("business_information", {})
    if not business_info:
        business_info = await get_business_info(business_id) or {}
        user_state["business_information"] = business_info

    products_cache = user_state.get("products", {})
    product_price = None

    if product_name and product_name.strip().upper() != "NONE":
        for cache in products_cache.values():
            for p in cache.get("retrieved_results", []):
                pname = p.get("name") or p.get("product_name", "")
                if pname and pname.lower() == product_name.lower():
                    product_name = pname
                    product_price = p.get("price")
                    break
            if product_price is not None:
                break

    if (not product_name or product_name.strip().upper() == "NONE") and products_cache:
        latest_product_key = list(products_cache.keys())[0]
        latest_product_data = products_cache[latest_product_key]
        products = latest_product_data.get("retrieved_results", [])
        if products:
            product_info = products[0]
            product_name = product_info.get("name") or product_info.get("product_name")
            product_price = product_info.get("price")

    # Build dynamic prompt with business and product details
    dynamic_prompt_parts = []

    if business_info:
        dynamic_prompt_parts.append("\n**BUSINESS ACCOUNT DETAILS:**")
        if business_info.get("bank_name"):
            dynamic_prompt_parts.append(f"Bank Name: {business_info['bank_name']}")
        if business_info.get("bank_account_name"):
            dynamic_prompt_parts.append(f"Account Name: {business_info['bank_account_name']}")
        if business_info.get("bank_account_number"):
            dynamic_prompt_parts.append(f"Account Number: {business_info['bank_account_number']}")

    if product_name:
        dynamic_prompt_parts.append("\n**PRODUCT DETAILS:**")
        dynamic_prompt_parts.append(f"Product Name: {product_name}")
        dynamic_prompt_parts.append(f"Product Price: ${product_price}" if product_price is not None else "Product Price: Unknown")

    dynamic_prompt = "\n".join(dynamic_prompt_parts)
    
    # Update agent system prompt dynamically
    payment_verification_agent_base.add_data(data=dynamic_prompt, chat_history=user_state.get("chat_history", []))
    
    # Create new agent instance with updated prompt (or use message history)
    deps = PaymentVerificationDeps(
        user_id=user_id,
        business_id=business_id,
        user_state=user_state
    )
    
    result = await payment_verification_agent.run(customer_message, deps=deps)
    response = result.output
    
    user_state.setdefault("chat_history", []).extend([
    ModelRequest(parts=[UserPromptPart(content=customer_message)]),
    ModelResponse(parts=[TextPart(content=response)])])
    
    
    if receipt_data:
        user_state["receipt_data"] = receipt_data

    await save_user_state(user_id, business_id, user_state)

    return response
