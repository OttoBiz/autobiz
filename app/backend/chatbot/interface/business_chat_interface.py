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
from backend.struct import BusinessRequest, CentralAgentInput, Customer, Vendor, Product
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
    reply_context: Optional[Dict[str, str]] = None  # customer_id, product_name, order_id when replying to inbox

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
- When reply_context is provided (customer_id, product_name, order_id), treat the message as a reply to that thread and route to central agent.
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
    state_key_id = business_request.logistic_id if business_request.logistic_id else business_request.vendor_id
    user_state = await get_user_state(state_key_id, state_key_id) or {}
    if "chat_history" not in user_state:
        user_state["chat_history"] = []

    reply_context = None
    if business_request.user_id and business_request.user_id not in (business_request.vendor_id, business_request.logistic_id):
        reply_context = {
            "customer_id": business_request.user_id,
            "product_name": business_request.product_name or "",
            "order_id": business_request.order_id or "",
        }
        if not reply_context["product_name"] and not reply_context["order_id"]:
            reply_context = {k: v for k, v in reply_context.items() if v}

    chat_history = user_state.get("chat_history", [])
    result = await business_chat_agent.run(
        business_request.message,
        deps=BusinessChatDeps(
            business_id=business_request.vendor_id,
            api_key=api_key,
            reply_context=reply_context,
        ),
        message_history=chat_history,
    )
    
    # Update chat history
    user_state["chat_history"].append(
        ModelRequest(parts=[UserPromptPart(content=business_request.message)])
    )
    
    if not result.output.for_central_agent and not (reply_context and reply_context.get("customer_id")):
        response = result.output.response
        user_state["chat_history"].append(
            ModelResponse(parts=[TextPart(content=response)])
        )
        await modify_user_state(state_key_id, state_key_id, user_state)
        return response

    agent_input = result.output.agent_input
    central_user_state = user_state

    if reply_context and reply_context.get("customer_id"):
        customer_id = reply_context["customer_id"]
        vendor_id = business_request.vendor_id
        central_user_state = await get_user_state(customer_id, vendor_id) or {}
        agent_input = await create_structured_input(
            sender="Vendor" if not business_request.logistic_id else "Logistics",
            recipient="Agent",
            message=business_request.message,
            customer=Customer(id=customer_id),
            business=Vendor(id=vendor_id),
            product=Product(id="", name=reply_context.get("product_name", ""), quantity=1, price=0, has_paid=False) if reply_context.get("product_name") else None,
            order_id=reply_context.get("order_id") or None,
        )

    background_tasks.add_task(
        run_central_agent,
        agent_input,
        central_user_state,
        vendor_only=True,
        debug=debug,
    )
    
    # Persist state using appropriate key
    await modify_user_state(state_key_id, state_key_id, user_state)
    return "Message processed. Coordinating with relevant parties. You'll be notified when the message has been processed successfully or we need more information from you."