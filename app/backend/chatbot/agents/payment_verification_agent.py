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


class PaymentVerificationDeps(BaseModel):
    """Dependencies for payment verification agent"""

    user_id: str
    business_id: str
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
5. If mismatch, ask customer to verify details

**OBJECTIVE**
- Verify payment transactions accurately and efficiently.
- Communicate clearly with all parties involved.""",
    deps_type=PaymentVerificationDeps,
)

payment_verification_agent = payment_verification_agent_base.agent


@payment_verification_agent.tool
async def notify_vendor_for_confirmation(
    ctx: RunContext[PaymentVerificationDeps],
    product_name: str,
    amount: float,
    transaction_reference: Optional[str] = None,
    receipt_details: Optional[str] = None,
) -> Dict[str, Any]:
    """Notify vendor to confirm payment verification"""
    return {
        "status": "vendor_notified",
        "message": "Vendor has been notified for payment confirmation",
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

    deps = PaymentVerificationDeps(user_id=user_id, business_id=business_id)

    # Build verification prompt
    verification_prompt = f"""Customer message: {customer_message}

{dynamic_prompt}

**VERIFICATION TASK:**
1. Extract payment details from the customer message and receipt data
2. Compare receipt details with business account information above
3. Compare payment amount with product price above
4. If everything matches (account number, account name, bank name, and amount), use notify_vendor_for_confirmation tool
5. If there's a mismatch, ask customer to verify the details

Receipt data: {receipt_data or 'Not provided'}

**IMPORTANT:** Only call notify_vendor_for_confirmation if:
- Receipt account number matches business account number
- Receipt account name matches business account name
- Receipt bank name matches business bank name
- Receipt amount matches product price (allow small variance)
"""

    result = await payment_verification_agent.run(verification_prompt, deps=deps)
    response = result.output

    # Check if vendor notification should be triggered
    if product_name and product_price and background_tasks:
        response_lower = response.lower()
        verification_keywords = ["verified", "match", "confirmed", "correct", "matches"]
        if any(keyword in response_lower for keyword in verification_keywords):
            agent_input = await create_structured_input(
                sender="agent",
                recipient="vendor",
                message=(
                    f"Payment verification request: Customer claims payment for product "
                    f"'{product_name}', Amount: ${product_price}. "
                    f"Receipt details: {receipt_data or customer_message}. "
                    f"Please confirm if payment was received."
                ),
            )
            background_tasks.add_task(
                run_central_agent,
                agent_input,
                user_state,
                vendor_only=True,
                debug=debug,
            )

    # Update user state
    user_state["chat_history"].append(
        {"role": "user", "name": "customer", "content": customer_message}
    )
    user_state["chat_history"].append(
        {"role": "assistant", "name": "payment_verification_agent", "content": response}
    )

    if receipt_data:
        user_state["receipt_data"] = receipt_data

    await save_user_state(user_id, business_id, user_state)

    return response
