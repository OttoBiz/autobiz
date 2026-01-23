"""
Business Chat Interface - Handles business owner interactions
Converted to Pydantic AI
"""
from fastapi import BackgroundTasks
from typing import Optional, Dict, Any
from .base_agent import BaseAgent
from .central_agent import run_central_agent
from .central_agent_utils import create_structured_input
from .agent_utils import get_or_create_user_state, save_user_state, format_chat_history
from backend.db.cache_utils import get_user_state, modify_user_state
from backend.struct import BusinessRequest
from pydantic import BaseModel


class BusinessChatDeps(BaseModel):
    """Dependencies for business chat"""
    business_id: str
    api_key: Optional[str] = None


# Initialize business chat agent
business_chat_agent_base = BaseAgent(
    system_prompt="""You are an AI assistant for business owners.

**YOUR JOB**
- Help business owners respond to customer inquiries
- Coordinate with central agent for multi-party communications
- Provide business insights and support

**RULES**
- Be professional and helpful
- Route complex communications to central agent
- Keep responses concise and actionable""",
    deps_type=BusinessChatDeps
)

business_chat_agent = business_chat_agent_base.agent


async def business_chat(
    business_request: BusinessRequest,
    background_tasks: BackgroundTasks,
    debug: bool = False
) -> Optional[str]:
    """
    Handle business chat messages.
    
    Args:
        business_request: Business request
        background_tasks: Background tasks
        debug: Debug mode
        
    Returns:
        Response message or None if handled in background
    """
    # Get business state
    user_state = await get_user_state(business_request.vendor_id, business_request.vendor_id)
    
    if not user_state:
        user_state = {"chat_history": []}
    
    chat_history = user_state.get("chat_history", [])
    
    # Check if this is a response to central agent communication
    if business_request.message_type and business_request.message_type != "General":
        # Route to central agent
        agent_input = await create_structured_input(
            sender=business_request.sender,
            recipient="agent",
            message=business_request.message,
            product_name=business_request.product_name or "",
            price=business_request.product_price or "",
            customer_id=business_request.user_id,
            business_id=business_request.vendor_id,
            logistic_id=business_request.logistic_id,
            message_type=business_request.message_type
        )
        
        # Update chat history
        user_state["chat_history"].append({
            "role": "user",
            "name": "business",
            "content": business_request.message
        })
        
        # Run central agent in background
        background_tasks.add_task(
            run_central_agent,
            agent_input,
            user_state,
            vendor_only=True,
            debug=debug
        )
        
        await save_user_state(business_request.vendor_id, business_request.vendor_id, user_state)
        return "Message processed. Coordinating with relevant parties..."
    
    # Regular business chat
    deps = BusinessChatDeps(
        business_id=business_request.vendor_id,
        api_key=None
    )
    
    prompt = f"""Business message: {business_request.message}

{format_chat_history(chat_history) if chat_history else 'No previous conversation'}

Provide a helpful response."""
    
    result = await business_chat_agent.run(prompt, deps=deps)
    response = result.output
    
    # Update chat history
    user_state["chat_history"].append({
        "role": "user",
        "name": "business",
        "content": business_request.message
    })
    user_state["chat_history"].append({
        "role": "assistant",
        "name": "ai",
        "content": response
    })
    
    await save_user_state(business_request.vendor_id, business_request.vendor_id, user_state)
    
    return response