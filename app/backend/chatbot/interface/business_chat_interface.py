"""
Business Chat Interface - Handles business owner interactions
Converted to Pydantic AI with analytics and inventory tools
"""
from fastapi import BackgroundTasks
from typing import Optional, Dict, Any, List
from pydantic_ai import RunContext
from backend.chatbot.agents.base_agent import BaseAgent
from backend.chatbot.agents.central_agent import run_central_agent
from backend.chatbot.agents.central_agent_utils import create_structured_input
from backend.chatbot.utils.agent_utils import format_chat_history
from backend.db.cache_utils import get_user_state, modify_user_state
from backend.db.db_utils import (
    get_business_analytics,
    get_inventory,
    update_product_stock,
    get_low_stock_products
)
from backend.struct import BusinessRequest, CentralAgentInput
from pydantic import BaseModel, Field
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

class BusinessChatDeps(BaseModel):
    """Dependencies for business chat"""
    business_id: str
    api_key: Optional[str] = None

class OutputBusinessChat(BaseModel):
    """Output for business chat"""
    response: Optional[str] = Field(..., description="Response to business owner message")
    for_central_agent: bool = False
    agent_input: Optional[CentralAgentInput] = Field(..., description="Input for central agent if for_central_agent is True")

# Initialize business chat agent
business_chat_agent_base = BaseAgent(
    system_prompt="""You are an AI assistant for business owners.

**YOUR JOB**
- Help business owners respond to customer inquiries
- Coordinate with central agent for multi-party communications
- Provide business analytics and insights
- Manage inventory and product availability

**RULES**
- Be professional and helpful
- Route complex communications to central agent
- Use analytics tools to provide data-driven insights
- Use inventory tools to manage stock levels
- Keep responses concise and actionable""",
    deps_type=BusinessChatDeps,
    output_type=OutputBusinessChat
)

business_chat_agent = business_chat_agent_base.agent


# Business Analytics Tool
@business_chat_agent.tool
async def get_business_analytics_tool(
    ctx: RunContext[BusinessChatDeps],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Dict[str, Any]:
    """Get business analytics including sales, orders, revenue, and top products"""
    try:
        return await get_business_analytics(ctx.deps.business_id, start_date=start_date, end_date=end_date)
    except Exception as e:
        return {"error": f"Analytics unavailable: {e}", "sales": {}, "orders": {}, "top_products": []}


# Inventory Management Tools
@business_chat_agent.tool
async def get_inventory_info(
    ctx: RunContext[BusinessChatDeps]
) -> List[Dict[str, Any]]:
    """Get current inventory information including stock levels and status"""
    try:
        return await get_inventory(ctx.deps.business_id)
    except Exception as e:
        return [{"error": f"Inventory unavailable: {e}"}]


@business_chat_agent.tool
async def update_product_availability(
    ctx: RunContext[BusinessChatDeps],
    product_id: str,
    stock_quantity: int
) -> Dict[str, Any]:
    """Update product stock quantity/availability"""
    try:
        updated = await update_product_stock(product_id, stock_quantity)
        if not updated:
            return {"error": "Product not found"}
        return {"success": True, "product": updated, "message": f"Stock updated to {stock_quantity} units"}
    except Exception as e:
        return {"error": f"Update failed: {e}"}


@business_chat_agent.tool
async def get_low_stock_alerts(
    ctx: RunContext[BusinessChatDeps],
    threshold: int = 10
) -> List[Dict[str, Any]]:
    """Get products with low stock levels that need restocking"""
    try:
        return await get_low_stock_products(ctx.deps.business_id, threshold)
    except Exception as e:
        return [{"error": f"Low stock check unavailable: {e}"}]


async def business_chat(
    business_request: BusinessRequest,
    background_tasks: BackgroundTasks,
    api_key: Optional[str] = None,
    debug: bool = False
) -> Optional[str]:
    """
    Handle business chat messages.
    Supports both business owners and logistics companies.
    
    Args:
        business_request: Business request (can be business or logistics)
        background_tasks: Background tasks
        api_key: Optional API key
        debug: Debug mode
        
    Returns:
        Response message or None if handled in background
    """
    # Determine state key: use logistic_id if present (for logistics), otherwise vendor_id (for business)
    state_key_id = business_request.logistic_id if business_request.logistic_id else business_request.vendor_id
    state_key_type = "logistics" if business_request.logistic_id else "business"
    
    # Get state using appropriate key
    user_state = await get_user_state(state_key_id, state_key_id) or {}
    
    # Initialize chat_history if not present
    if "chat_history" not in user_state:
        user_state["chat_history"] = []
    
    chat_history = user_state.get("chat_history", [])
    
    # Run business chat agent
    result = await business_chat_agent.run(
        business_request.message, 
        deps=BusinessChatDeps(business_id=business_request.vendor_id, api_key=api_key),
        message_history=chat_history
    )
    
    # Update chat history
    user_state["chat_history"].append(
        ModelRequest(parts=[UserPromptPart(content=business_request.message)])
    )
    
    if not result.output.for_central_agent:
        response = result.output.response
        user_state["chat_history"].append(
            ModelResponse(parts=[TextPart(content=response)])
        )
        # Persist state using appropriate key
        await modify_user_state(state_key_id, state_key_id, user_state)
        return response

    # Run central agent in background
    background_tasks.add_task(
        run_central_agent,
        result.output.agent_input,
        user_state,
        vendor_only=True,
        debug=debug
    )
    
    # Persist state using appropriate key
    await modify_user_state(state_key_id, state_key_id, user_state)
    return "Message processed. Coordinating with relevant parties. You'll be notified when the message has been processed successfully or we need more information from you."