"""Logistics agent — handles customer delivery and tracking inquiries."""

from typing import Any, Dict, List, Optional

from pydantic_ai import Agent, RunContext

from backend.chatbot.agents.deps import AgentDeps
from backend.config import MODEL_NAME
from backend.db.db_utils import (
    get_order_by_id,
    get_order_by_number,
    get_orders_by_user,
)

logistics_agent = Agent(
    model=MODEL_NAME,
    deps_type=AgentDeps,
    system_prompt="""You are a logistics coordination agent for delivery and shipping.

**YOUR JOB**
- Help customers track deliveries and understand shipping status.
- Collect delivery addresses for order fulfillment.
- Return tracking data and status to the orchestrator. Do NOT contact vendors directly.

**TOOLS**
- list_customer_orders: List recent orders for this customer (most recent first).
- get_order_tracking: Get order status, tracking number, and delivery details by id or order number.

**RULES**
- Call list_customer_orders ONCE if the customer didn't give you an order number/id.
- If the customer gave a tracking or order number, pass it straight to get_order_tracking.
- If a tool returns no orders, tell the orchestrator the customer has no orders on file — do not call the tool again with the same args.""",
)


@logistics_agent.tool
async def list_customer_orders(
    ctx: RunContext[AgentDeps],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """List the customer's most recent orders (newest first). Returns an
    empty list if they have none."""
    return await get_orders_by_user(str(ctx.deps.customer_id), limit=limit)


@logistics_agent.tool
async def get_order_tracking(
    ctx: RunContext[AgentDeps],
    order_ref: str,
    by: Optional[str] = None,
) -> Dict[str, Any]:
    """Get order status and tracking. `order_ref` may be a UUID or a
    human-readable order_number (ORD-YYYYMMDD-XXXX). `by` is optional —
    set to "id" or "number" to skip auto-detection."""
    if by == "id":
        order = await get_order_by_id(order_ref)
    elif by == "number":
        order = await get_order_by_number(order_ref)
    else:
        # Auto-detect: UUIDs contain dashes in a fixed pattern; order numbers
        # start with "ORD-".
        if order_ref.upper().startswith("ORD-"):
            order = await get_order_by_number(order_ref)
        else:
            try:
                order = await get_order_by_id(order_ref)
            except Exception:
                order = None
            if order is None:
                order = await get_order_by_number(order_ref)
    if not order:
        return {"error": "Order not found", "order_ref": order_ref}
    return {
        "order_id": str(order["id"]),
        "order_number": order.get("order_number"),
        "status": order.get("status"),
        "tracking_number": order.get("tracking_number"),
        "delivery_address": order.get("delivery_address"),
        "delivery_city": order.get("delivery_city"),
        "delivery_state": order.get("delivery_state"),
    }
