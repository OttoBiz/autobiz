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
- Verify payments by confirming transaction details match business account and product prices.
- Compare receipt details with business account information and product prices.
- If details match, send confirmation message to vendor.
- Handle communication between customer and vendor until payment is verified.

**VERIFICATION PROCESS**
1. Extract payment details from receipt/document
2. Compare with business account details (bank name, account number, account name)
3. Compare amount with product price
4. If everything matches, notify vendor for final confirmation
5. If mismatch, ask customer to verify details and resend the appropriate document or receipt.

**OBJECTIVE**
- Verify payment transactions accurately and efficiently.
- Communicate clearly with all parties involved.

**IMPORTANT:** Only call notify_vendor_for_confirmation if:
- Receipt account number matches business account number
- Receipt account name matches business account name  
- Receipt bank name matches business bank name
- Receipt amount matches product price (allow small variance)""",
    deps_type=PaymentVerificationDeps
)

payment_verification_agent = payment_verification_agent_base.agent


@payment_verification_agent.tool
async def notify_vendor_for_confirmation(
    ctx: RunContext[PaymentVerificationDeps],
    product_name: str,
    amount: float,
    transaction_reference: Optional[Dict[Any],str] = None,
    receipt_details: Optional[str] = None
) -> Dict[str, Any]:
    """Notify vendor to confirm payment verification"""
    # This will trigger central agent to send message to vendor
    agent_input = await create_structured_input(
        sender="agent",
        recipient="vendor",
        message=f"Payment verification request: Customer claims payment for product '{product_name}', Amount: ${amount}. Receipt details: {receipt_details}, Transaction reference: {transaction_reference}. Please confirm if payment was received.",
        product_name=product_name,
        price=str(amount) if amount else "",
        customer_id=ctx.deps.user_id,
        business_id=ctx.deps.business_id
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
        "message": "Vendor has been notified for payment confirmation. Inform customer to wait for confirmation from vendor."
    }


async def run_verification_agent(
    customer_message: str,
    user_id: str,
    business_id: str,
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
        user_state: Optional user state
        background_tasks: Background tasks
        receipt_data: Extracted receipt data from file processing
        debug: Debug mode

    Returns:
        Verification response message
    """
    if not user_state:
        user_state = await get_or_create_user_state(user_id, business_id)

    # Get business information
    business_info = user_state.get("business_information", {})
    if not business_info:
        business_info = await get_business_info(business_id) or {}
        user_state["business_information"] = business_info

    # Get product information from user state
    products_cache = user_state.get("products", {})
    product_name = None
    product_price = None

    if products_cache:
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
        dynamic_prompt_parts.append(f"Product Price: ${product_price}")

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
    
    # Update user state
    user_state["chat_history"].extend([
    ModelRequest(parts=[UserPromptPart(content=customer_message)]),
    ModelResponse(parts=[TextPart(content=response)])])
    
    
    if receipt_data:
        user_state["receipt_data"] = receipt_data

    await save_user_state(user_id, business_id, user_state)

    return response
