"""
Logistics Agent - Handles customer logistics and delivery inquiries
"""

from typing import Any, Dict, Optional

from fastapi import BackgroundTasks
from pydantic import BaseModel

from backend.chatbot.utils.agent_utils import get_or_create_user_state, save_user_state
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from .base_agent import BaseAgent


class LogisticsDeps(BaseModel):
    """Dependencies for logistics agent"""

    user_id: str
    business_id: str


# Initialize logistics agent
logistics_agent_base = BaseAgent(
    system_prompt="""You are a logistics coordination agent that handles delivery and shipping inquiries.

**YOUR JOB**
- Help customers track their deliveries and understand shipping status.
- Collect delivery addresses when needed for order fulfillment.
- Coordinate with the business to arrange logistics for customer orders.
- Provide estimated delivery times and answer shipping-related questions.

**OBJECTIVE**
- Ensure customers have clarity on their delivery status.
- Collect and confirm delivery details needed to proceed with shipping.""",
    deps_type=LogisticsDeps,
)

logistics_agent = logistics_agent_base.agent


async def run_logistics_agent(
    customer_message: str,
    user_id: str,
    business_id: str,
    user_state: Optional[Dict[str, Any]] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    debug: bool = False,
    **kwargs,
) -> str:
    """
    Run logistics agent to handle delivery and shipping inquiries.

    Args:
        customer_message: Customer message about logistics/delivery
        user_id: User ID
        business_id: Business ID
        user_state: Optional user state dict
        background_tasks: Background tasks
        debug: Debug mode

    Returns:
        Response message string
    """
    if not user_state:
        user_state = await get_or_create_user_state(user_id, business_id)

    deps = LogisticsDeps(user_id=user_id, business_id=business_id)

    prompt = f"""Customer logistics inquiry: {customer_message}

Help the customer with their delivery or shipping question, collect any missing details (e.g. address), and coordinate next steps."""

    result = await logistics_agent.run(prompt, deps=deps)
    response = result.output

    user_state.setdefault("chat_history", []).extend([
        ModelRequest(parts=[UserPromptPart(content=customer_message)]),
        ModelResponse(parts=[TextPart(content=response)]),
    ])

    await save_user_state(user_id, business_id, user_state)

    return response
