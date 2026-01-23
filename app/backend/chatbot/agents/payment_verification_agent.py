"""
Payment Verification Agent - Verifies customer payments
Converted to pydantic_ai with media processing support
"""
from typing import Dict, Any, Optional
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from .base_agent import BaseAgent
from .agent_utils import get_or_create_user_state, save_user_state
from .media_processing_agent import process_receipt_image, process_image
from fastapi import BackgroundTasks


class PaymentVerificationDeps(BaseModel):
    """Dependencies for payment verification agent"""
    user_id: str
    business_id: str
    api_key: Optional[str] = None


# Initialize payment verification agent
payment_verification_agent_base = BaseAgent(
    system_prompt="""You are a payment verification assistant.

**YOUR JOB**
- Verify payments by confirming transaction details provided by customers.
- Provide transaction, product and bank details to vendors for confirmation.
- Handle communication between customer and vendor until payment is verified.

**OBJECTIVE**
- Verify payment transactions accurately and efficiently.
- Communicate clearly with all parties involved.""",
    deps_type=PaymentVerificationDeps
)

payment_verification_agent = payment_verification_agent_base.agent


async def run_verification_agent(
    customer_message: str,
    user_id: str,
    business_id: str,
    user_state: Optional[Dict[str, Any]] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    debug: bool = False,
    **kwargs
) -> str:
    """
    Run payment verification agent.
    
    Args:
        customer_message: Customer message with payment details
        user_id: User ID
        business_id: Business ID
        user_state: Optional user state
        background_tasks: Background tasks
        debug: Debug mode
        
    Returns:
        Verification response message
    """
    if not user_state:
        user_state = await get_or_create_user_state(user_id, business_id)
    
    deps = PaymentVerificationDeps(
        user_id=user_id,
        business_id=business_id
    )
    
    prompt = f"""Customer message: {customer_message}

Verify the payment details and confirm with the vendor if needed."""
    
    result = await payment_verification_agent.run(prompt, deps=deps)
    response = result.output
    
    # Update user state
    user_state["chat_history"].append({
        "role": "user",
        "name": "customer",
        "content": customer_message
    })
    user_state["chat_history"].append({
        "role": "assistant",
        "name": "payment_verification_agent",
        "content": response
    })
    
    await save_user_state(user_id, business_id, user_state)
    
    return response
