"""
Logistics Agent - Handles delivery and logistics coordination
Converted to pydantic_ai
"""
from typing import Dict, Any, Optional
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from .base_agent import BaseAgent
from .agent_utils import get_or_create_user_state, save_user_state
from fastapi import BackgroundTasks


class LogisticsAgentDeps(BaseModel):
    """Dependencies for logistics agent"""
    user_id: str
    business_id: str
    logistic_id: Optional[str] = None
    api_key: Optional[str] = None


# Initialize logistics agent
logistics_agent_base = BaseAgent(
    system_prompt="""You are a logistics coordination assistant.

**YOUR JOB**
- Coordinate product delivery between customers, vendors, and logistics companies.
- Collect delivery addresses and preferences.
- Track orders and provide updates.
- Handle delivery-related communications.

**OBJECTIVE**
- Ensure seamless product delivery coordination.""",
    deps_type=LogisticsAgentDeps
)

logistics_agent = logistics_agent_base.agent


async def run_logistics_agent(
    customer_message: str,
    user_id: str,
    business_id: str,
    user_state: Optional[Dict[str, Any]] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    debug: bool = False,
    **kwargs
) -> str:
    """
    Run logistics agent.
    
    Args:
        customer_message: Customer message about delivery
        user_id: User ID
        business_id: Business ID
        user_state: Optional user state
        background_tasks: Background tasks
        debug: Debug mode
        
    Returns:
        Logistics response message
    """
    if not user_state:
        user_state = await get_or_create_user_state(user_id, business_id)
    
    logistic_id = kwargs.get("logistic_id")
    
    deps = LogisticsAgentDeps(
        user_id=user_id,
        business_id=business_id,
        logistic_id=logistic_id
    )
    
    prompt = f"""Customer message: {customer_message}

Coordinate delivery logistics and collect necessary information."""
    
    result = await logistics_agent.run(prompt, deps=deps)
    response = result.output
    
    # Update user state
    user_state["chat_history"].append({
        "role": "user",
        "name": "customer",
        "content": customer_message
    })
    user_state["chat_history"].append({
        "role": "assistant",
        "name": "logistics_agent",
        "content": response
    })
    
    await save_user_state(user_id, business_id, user_state)
    
    return response
