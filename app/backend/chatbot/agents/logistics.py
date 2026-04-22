"""Logistics agent — handles customer delivery and tracking inquiries."""

from typing import Any, Dict, Optional

from pydantic_ai import Agent, RunContext

from backend.chatbot.agents.deps import AgentDeps
from backend.config import MODEL_NAME
from backend.db.db_utils import get_order_by_id

logistics_agent = Agent(
    model=MODEL_NAME,
    deps_type=AgentDeps,
    system_prompt="""You are a logistics coordination agent for delivery and shipping.

**YOUR JOB**
- Help customers track deliveries and understand shipping status.
- Collect delivery addresses for order fulfillment.
- Return tracking data and status to the orchestrator. Do NOT contact vendors directly.

**TOOLS**
- get_order_for_product: Get order_id for a purchased product from processes.
- get_order_tracking: Get order status, tracking number, and delivery details.""",
)


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
