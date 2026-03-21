"""
Logistics Agent - Handles customer logistics and delivery inquiries
"""

from typing import Any, Dict, List, Optional

from pydantic_ai import RunContext

from backend.chatbot.agents.central_agent import run_central_agent
from backend.chatbot.agents.central_agent_utils import create_structured_input
from backend.chatbot.agents.main_agent import AgentDeps
from backend.db.db_utils import get_order_by_id
from backend.struct import Customer, Vendor

from .base_agent import BaseAgent


logistics_agent_base = BaseAgent(
    system_prompt="""You are a logistics coordination agent for delivery and shipping.

**YOUR JOB**
- Help customers track deliveries and understand shipping status.
- Collect delivery addresses for order fulfillment.
- Coordinate with vendor/logistics via notify_central_agent. Always pass order_id when available.

**TOOLS**
- get_order_for_product: Get order_id for a purchased product from processes.
- get_order_tracking: Get order status, tracking number, and delivery details.
- notify_central_agent: Request info from vendor/logistics. Include order_id and product_name when available.""",
    deps_type=AgentDeps,
)

logistics_agent = logistics_agent_base.agent


@logistics_agent.tool
async def get_order_for_product(
    ctx: RunContext[AgentDeps],
    product_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Get order_id for a purchased product from processes."""
    processes = ctx.deps.state.get("processes", {})
    if product_name and product_name in processes:
        oid = processes[product_name].get("order_id")
        if oid:
            return {"order_id": oid, "product_name": product_name}
    for pname, proc in processes.items():
        if proc.get("order_id"):
            return {"order_id": proc["order_id"], "product_name": pname}
    return {"order_id": None, "product_name": product_name}


@logistics_agent.tool
async def get_order_tracking(
    ctx: RunContext[AgentDeps],
    order_id: str,
) -> Dict[str, Any]:
    """Get order status, tracking number, and delivery details."""
    order = await get_order_by_id(order_id)
    if not order:
        return {"error": "Order not found", "order_id": order_id}
    return {
        "order_id": str(order["id"]),
        "order_number": order.get("order_number"),
        "status": order.get("status"),
        "tracking_number": order.get("tracking_number"),
        "delivery_address": order.get("delivery_address"),
        "delivery_city": order.get("delivery_city"),
        "delivery_state": order.get("delivery_state"),
    }


@logistics_agent.tool
async def notify_central_agent(
    ctx: RunContext[AgentDeps],
    message: str,
    recipient: str = "Vendor",
    order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Notify central agent. Pass order_id when available for better context."""
    try:
        full_msg = f"[Order ID: {order_id}] {message}" if order_id else message
        agent_input = await create_structured_input(
            sender="Agent",
            recipient=recipient,
            message=full_msg,
            customer=Customer(id=ctx.deps.user_id),
            business=Vendor(id=ctx.deps.business_id),
            order_id=order_id,
        )
        await run_central_agent(event_message=agent_input)
        return {"status": "sent", "message": "Request sent. Awaiting response."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
