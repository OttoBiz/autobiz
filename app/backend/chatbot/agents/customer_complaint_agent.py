"""
Customer Complaint Agent - Handles customer complaints and feedback
Converted to pydantic_ai
"""

from typing import Any, Dict, Optional

from fastapi import BackgroundTasks
from pydantic import BaseModel
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from backend.chatbot.utils.agent_utils import get_or_create_user_state, save_user_state

from .base_agent import BaseAgent


class CustomerComplaintDeps(BaseModel):
    """Dependencies for customer complaint agent"""

    user_id: str
    business_id: str


# Initialize customer complaint agent
customer_complaint_agent_base = BaseAgent(
    system_prompt="""You are a customer service agent that handles customer complaints and feedback.

**YOUR JOB**
- Collect information about complaints/feedback and try to resolve issues.
- Refer customers to human agents when:
  - Issue is too complex
  - Customer demands refund
  - Product return or exchange is requested
  - Customer demands to speak with vendor directly

**OBJECTIVE**
- Resolve customer complaints efficiently.
- Escalate to human agents when necessary.""",
    deps_type=CustomerComplaintDeps,
)

customer_complaint_agent = customer_complaint_agent_base.agent


async def run_customer_complaint_agent(
    customer_message: str,
    product_name: str,
    user_id: str,
    business_id: str,
    user_state: Optional[Dict[str, Any]] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    debug: bool = False,
    **kwargs,
) -> tuple[str, Dict[str, Any]]:
    """
    Run customer complaint agent.

    Args:
        complaint: Customer complaint message
        product_name: Product name related to complaint
        user_id: User ID
        business_id: Business ID
        user_state: Optional user state
        background_tasks: Background tasks
        debug: Debug mode

    Returns:
        Tuple of (response_message, updated_user_state)
    """
    if not user_state:
        user_state = await get_or_create_user_state(user_id, business_id)

    deps = CustomerComplaintDeps(user_id=user_id, business_id=business_id)

    prompt = f"""Customer complaint: {customer_message}
Product: {product_name}

Address this complaint and provide resolution or escalate to human agent if needed."""

    result = await customer_complaint_agent.run(prompt, deps=deps)
    response = result.output

    # Update user state
    user_state["chat_history"].append(
        [
            ModelRequest(parts=[UserPromptPart(content=customer_message)]),
            ModelResponse(parts=[TextPart(content=response)]),
        ]
    )

    await save_user_state(user_id, business_id, user_state)

    return response, user_state
