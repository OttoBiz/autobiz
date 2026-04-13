"""
Logistics Agent - Handles customer logistics and delivery inquiries
"""

from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks
from pydantic import BaseModel
from pydantic_ai import RunContext

from backend.chatbot.agents.central_agent import run_central_agent
from backend.chatbot.agents.central_agent_utils import (
    coerce_entity,
    create_structured_input,
    ensure_central_process,
)
from backend.chatbot.utils.agent_utils import get_or_create_user_state, save_user_state
from backend.db.cache_utils import get_user_state, modify_user_state
from backend.db.db_utils import get_order_by_id
from backend.struct import Customer, EntityType, Product, TaskType, Vendor
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from .base_agent import BaseAgent


class LogisticsDeps(BaseModel):
    """Dependencies for logistics agent"""

    user_id: str
    business_id: str
    product_name: Optional[str] = None
    products_cache: Optional[Dict[str, Any]] = None
    processes: Optional[Dict[str, Any]] = None


# Initialize logistics agent
logistics_agent_base = BaseAgent(
    system_prompt="""You are the **logistics specialist**: tracking, ETAs, delivery coordination.

**Workflow**
1. Call `get_order_for_product` to find the order_id for the product in question.
2. With an order_id, call `get_order_tracking` for status, dispatch rider's phone number, tracking number, and delivery details.
3. If delivery address is missing or needs confirmation, ask the customer directly.
4. When you need to escalate (e.g. delayed shipment, missing tracking), call `notify_central_agent` with the order_id.

**Rules**
- Never guess tracking numbers or ETAs. If unknown, tell the customer what you are doing next.
- Tone: reassuring, specific, concise.""",
    deps_type=LogisticsDeps,
)

logistics_agent = logistics_agent_base.agent


@logistics_agent.tool
async def get_order_for_product(
    ctx: RunContext[LogisticsDeps],
    product_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Get order_id for a purchased product from processes. Pass order_id to notify_central_agent."""
    processes = ctx.deps.processes or {}
    pname = (product_name or ctx.deps.product_name or "").strip()
    for _pid, proc in processes.items():
        if not isinstance(proc, dict):
            continue
        pn = (proc.get("product_name") or "").strip()
        if pname and pn:
            if pname.lower() not in pn.lower() and pn.lower() not in pname.lower():
                continue
        oid = proc.get("order_id")
        if oid:
            return {"order_id": oid, "product_name": pn or pname, "process_id": _pid}
    return {"order_id": None, "product_name": pname or None}


@logistics_agent.tool
async def get_order_tracking(
    ctx: RunContext[LogisticsDeps],
    order_id: str,
) -> Dict[str, Any]:
    """Get order status, tracking number, and delivery details. Use order_id from get_order_for_product."""
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
async def get_product_from_cache(
    ctx: RunContext[LogisticsDeps],
) -> List[Dict[str, Any]]:
    """Get products from cache to identify which product the customer is asking about for delivery."""
    cache = ctx.deps.products_cache or {}
    for key, data in cache.items():
        results = data.get("retrieved_results", [])
        if results:
            return [{"name": p.get("name", p.get("product_name")), "price": p.get("price")} for p in results]
    return []


@logistics_agent.tool
async def notify_central_agent(
    ctx: RunContext[LogisticsDeps],
    message: str,
    recipient: str = "Vendor",
    order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Notify central agent. Pass order_id when available (from get_order_for_product) for better context."""
    try:
        full_msg = message
        if order_id:
            full_msg = f"[Order ID: {order_id}] {message}"
        us = await get_user_state(ctx.deps.user_id, ctx.deps.business_id) or {}
        pid = ensure_central_process(
            us,
            task_type=TaskType.LOGISTICS_COORDINATION,
            customer_id=ctx.deps.user_id,
            vendor_id=ctx.deps.business_id,
            product_name=ctx.deps.product_name or "",
            order_id=order_id,
        )
        await modify_user_state(ctx.deps.user_id, ctx.deps.business_id, us)
        agent_input = await create_structured_input(
            sender=EntityType.AGENT,
            recipient=coerce_entity(recipient),
            message=full_msg,
            customer=Customer(id=ctx.deps.user_id),
            business=Vendor(id=ctx.deps.business_id),
            order_id=order_id,
            product=Product(id="", name=ctx.deps.product_name or "", quantity=1, price=0.0)
            if ctx.deps.product_name
            else None,
            process_id=pid,
            task_type=TaskType.LOGISTICS_COORDINATION,
        )
        await run_central_agent(
            event_message=agent_input,
            user_state=us,
            caller_agent="logistics_agent.notify_central",
        )
        return {"status": "sent", "message": "Request sent. Customer will be updated when we receive a response."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def run_logistics_agent(
    customer_message: str,
    user_id: str,
    business_id: str,
    product_name: Optional[str] = None,
    user_state: Optional[Dict[str, Any]] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    debug: bool = False,
    append_chat_history: bool = True,
    **kwargs,
) -> str:
    """
    Run logistics agent to handle delivery and shipping inquiries.

    Args:
        customer_message: Customer message about logistics/delivery
        user_id: User ID
        business_id: Business ID
        product_name: Product being discussed
        user_state: Optional user state dict
        background_tasks: Background tasks
        debug: Debug mode

    Returns:
        Response message string
    """
    if not user_state:
        user_state = await get_or_create_user_state(user_id, business_id)

    products_cache = user_state.get("products", {})
    processes = user_state.get("processes", {})
    product_context = f"\nProduct for delivery: {product_name}" if product_name else ""
    order_id = kwargs.get("order_id")
    order_ctx = f"\nOrder ID: {order_id}" if order_id else ""

    deps = LogisticsDeps(
        user_id=user_id,
        business_id=business_id,
        product_name=product_name,
        products_cache=products_cache,
        processes=processes,
    )

    result = await logistics_agent.run(customer_message + product_context + order_ctx, deps=deps)
    response = result.output

    if append_chat_history:
        user_state.setdefault("chat_history", []).extend([
            ModelRequest(parts=[UserPromptPart(content=customer_message)]),
            ModelResponse(parts=[TextPart(content=response)]),
        ])

    await save_user_state(user_id, business_id, user_state)

    return response
