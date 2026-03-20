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
    logistic_id: str = ""
    api_key: Optional[str] = None


class ReplyContext(BaseModel):
    """Reply context extracted from chat history when business is replying about a customer/order/product."""
    customer_id: Optional[str] = None
    vendor_id: Optional[str] = None  # Business/vendor for the order (when logistics replying)
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    order_id: Optional[str] = None
    order_number: Optional[str] = None
    quantity: Optional[int] = None
    product_attributes: Optional[Dict[str, Any]] = None


class OutputBusinessChat(BaseModel):
    """Output for business chat. Agent extracts reply_context from chat history when applicable."""
    response: Optional[str] = Field(default=None, description="Response to business owner (or None if routing to central)")
    for_central_agent: bool = False
    message_for_central: Optional[str] = Field(default=None, description="Message to send to central agent if for_central_agent")
    reply_context: Optional[ReplyContext] = Field(default=None, description="Extracted from chat: customer_id, product_name, order_id when replying about a specific thread")
    
# Initialize business chat agent
business_chat_agent_base = BaseAgent(
    system_prompt="""You are an AI assistant for business owners and logistics.

**YOUR JOB**
1. Help with business analytics, inventory, and product availability (use tools).
2. When the business/logistics is replying about a customer, order, or product: extract reply_context from the chat history (inbox messages include [Customer: X | Product: Y | Order: Z]) and route to central agent.

**EXTRACTING REPLY CONTEXT**
- Chat history contains inbox messages with structured context: [Customer: {id} | Product: {name} | Order: {id/number}]
- When the user's message is a reply (e.g. "Yes confirmed", "Shipped", "Delivered"), extract customer_id, product_name, order_id from the most recent relevant inbox message.
- Set for_central_agent=True and populate reply_context with extracted values.
- Set message_for_central to the user's message (or a clear paraphrase).

**RULES**
- If the user is querying analytics/inventory: respond directly, for_central_agent=False.
- If the user is replying to an inbox message about a customer/order: extract context, for_central_agent=True, reply_context filled.
- Be professional and concise.""",
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
    """Get business analytics for business including sales, orders, revenue, and top products"""
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
    Handle business/logistics chat. Agent extracts reply context from chat history.
    """
    state_key_id = business_request.logistic_id or business_request.vendor_id
    if not state_key_id:
        return "Error: vendor_id or logistic_id required"
    user_state = await get_user_state(state_key_id, state_key_id) or {}
    if "chat_history" not in user_state:
        user_state["chat_history"] = []

    vendor_id = business_request.vendor_id or business_request.logistic_id
    chat_history = list(user_state.get("chat_history", []))
    recent_inbox = business_request.recent_inbox or []
    for m in recent_inbox:
        content = m.get("message", "")
        ctx_parts = []
        if m.get("customer_id"):
            ctx_parts.append(f"Customer: {m['customer_id']}")
        if m.get("product_name"):
            ctx_parts.append(f"Product: {m['product_name']}")
        if m.get("order_id"):
            ctx_parts.append(f"Order: {m['order_id']}")
        if m.get("business_id"):
            ctx_parts.append(f"Vendor: {m['business_id']}")
        if ctx_parts:
            content = f"[{' | '.join(ctx_parts)}] {content}"
        chat_history.append(ModelRequest(parts=[UserPromptPart(content="[Inbox]")]))
        chat_history.append(ModelResponse(parts=[TextPart(content=content)]))
    result = await business_chat_agent.run(
        business_request.message,
        deps=BusinessChatDeps(
            business_id=vendor_id,
            logistic_id=business_request.logistic_id,
            api_key=api_key,
        ),
        message_history=chat_history,
    )

    user_state["chat_history"].append(
        ModelRequest(parts=[UserPromptPart(content=business_request.message)])
    )

    if not result.output.for_central_agent:
        response = result.output.response or "How can I help?"
        user_state["chat_history"].append(
            ModelResponse(parts=[TextPart(content=response)])
        )
        await modify_user_state(state_key_id, state_key_id, user_state)
        return response

    rc = result.output.reply_context
    msg = result.output.message_for_central or business_request.message
    if not rc or not rc.customer_id:
        user_state["chat_history"].append(
            ModelResponse(parts=[TextPart(content="I need more context. Which customer or order is this about? Please reply to the specific inbox message.")])
        )
        await modify_user_state(state_key_id, state_key_id, user_state)
        return "Could not determine which customer/order you're replying to. Please ensure you're replying in the context of an inbox message."

    biz_id = rc.vendor_id or vendor_id
    agent_input = await create_structured_input(
        sender="Vendor" if not business_request.logistic_id else "Logistics",
        recipient="Agent",
        message=msg,
        customer=Customer(id=rc.customer_id),
        business=Vendor(id=biz_id),
        product=Product(id=rc.product_id or "", name=rc.product_name or "", quantity=rc.quantity or 1, price=0, has_paid=False) if rc.product_name else None,
        order_id=rc.order_id or None,
    )
    central_user_state = await get_user_state(rc.customer_id, biz_id) or {}

    background_tasks.add_task(
        run_central_agent,
        agent_input,
        central_user_state,
        vendor_only=True,
        debug=debug,
    )
    await modify_user_state(state_key_id, state_key_id, user_state)
    return "Message processed. Coordinating with relevant parties."