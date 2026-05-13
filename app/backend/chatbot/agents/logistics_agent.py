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
from backend.db.db_utils import get_order_by_id, list_orders_for_customer_store
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
    process_id: Optional[str] = None
    resolved_order_id: Optional[str] = None


# Initialize logistics agent
logistics_agent_base = BaseAgent(
    system_prompt="""You are the **logistics specialist**: tracking, ETAs, delivery coordination.

**Workflow**
1. With an order_id (or process_id that has an order in session), call `get_order_tracking` for status, tracking number, and delivery details.
2. To list past purchases at this store from the database (by day or time window), call `list_customer_orders` with optional `on_date` (YYYY-MM-DD) or ISO `created_after` / `created_before`.
3. If delivery address is missing or needs confirmation, ask the customer directly.
4. When you need to escalate (e.g. delivery date and time alignment between customer and vendor+/- logistics company, 
delayed shipment, missing tracking), call `notify_central_agent` with the order_id to get feedback response from the vendor/logistics company.
if you need more information from the customer (i.e when they will be available for the delivery), you can't about it all at once and ask the customer for a seamless experience.

**Rules**
- Never guess tracking numbers or ETAs. If unknown, tell the customer what you are doing next.
- Tone: reassuring, specific, concise.""",
    deps_type=LogisticsDeps,
)

logistics_agent = logistics_agent_base.agent


def _slim_order_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in (
        "id", "user_id", "business_id", "order_number", "status", "total_amount",
        "tracking_number", "logistic_id", "delivery_address", "delivery_city", "delivery_state",
        "product_name",
        "created_at", "updated_at",
    ):
        v = row.get(k)
        if v is None:
            continue
        if k in ("id", "user_id", "business_id", "logistic_id"):
            out[k] = str(v)
        elif k in ("created_at", "updated_at") and hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    pa = row.get("product_attributes")
    if isinstance(pa, dict):
        out["product_attributes"] = pa
    meta = row.get("metadata")
    if isinstance(meta, dict) and meta:
        out["metadata"] = meta
    return out


@logistics_agent.tool
async def get_order_for_product(
    ctx: RunContext[LogisticsDeps],
    process_id: Optional[str] = None,
    order_id: Optional[str] = None,
    product_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve the order for a delivery request. Prefer passing `process_id` or `order_id` directly
    (both are visible in the session context injected at run time). Falls back to fuzzy-matching
    `product_name` across open processes. Returns `order_id` + `process_id` for use with
    `get_order_tracking` and `notify_central_agent`."""
    processes = ctx.deps.processes or {}

    # 1. Explicit process_id (from context or caller)
    focus = (process_id or getattr(ctx.deps, "process_id", None) or "").strip()
    if focus:
        raw = processes.get(focus)
        if isinstance(raw, dict) and raw.get("order_id"):
            return {
                "order_id": raw["order_id"],
                "product_name": (raw.get("product_name") or "").strip() or product_name,
                "process_id": focus,
            }

    # 2. Explicit order_id — scan processes for a match
    oid_in = (order_id or "").strip()
    if oid_in:
        for _pid, proc in processes.items():
            if isinstance(proc, dict) and str(proc.get("order_id") or "") == oid_in:
                return {
                    "order_id": oid_in,
                    "product_name": (proc.get("product_name") or "").strip() or product_name,
                    "process_id": _pid,
                }
        return {"order_id": oid_in, "product_name": product_name or None, "process_id": None}

    # 3. Fuzzy product name scan
    pname = (product_name or ctx.deps.product_name or "").strip()
    for _pid, proc in processes.items():
        if not isinstance(proc, dict):
            continue
        pn = (proc.get("product_name") or "").strip()
        if pname and pn and pname.lower() not in pn.lower() and pn.lower() not in pname.lower():
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
    ca, ua = order.get("created_at"), order.get("updated_at")
    return {
        "order_id": str(order["id"]),
        "order_number": order.get("order_number"),
        "status": order.get("status"),
        "tracking_number": order.get("tracking_number"),
        "product_name": order.get("product_name"),
        "product_attributes": order.get("product_attributes")
        if isinstance(order.get("product_attributes"), dict)
        else {},
        "delivery_address": order.get("delivery_address"),
        "delivery_city": order.get("delivery_city"),
        "delivery_state": order.get("delivery_state"),
        "created_at": ca.isoformat() if hasattr(ca, "isoformat") else ca,
        "updated_at": ua.isoformat() if hasattr(ua, "isoformat") else ua,
    }


@logistics_agent.tool
async def list_customer_orders(
    ctx: RunContext[LogisticsDeps],
    limit: int = 30,
    on_date: Optional[str] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
) -> Dict[str, Any]:
    """DB orders for this customer with this store. Filter by `on_date` (YYYY-MM-DD UTC) or ISO `created_after` / `created_before` to match a specific purchase time."""
    uid = (ctx.deps.user_id or "").strip()
    bid = (ctx.deps.business_id or "").strip()
    if not uid or not bid:
        return {"error": "Missing user or business context", "orders": []}
    rows = await list_orders_for_customer_store(
        uid,
        bid,
        limit=max(1, min(int(limit), 100)),
        on_date=(on_date or "").strip() or None,
        created_after_iso=(created_after or "").strip() or None,
        created_before_iso=(created_before or "").strip() or None,
    )
    return {"count": len(rows), "orders": [_slim_order_row(dict(r)) for r in rows]}


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
    process_id: Optional[str] = None,
    task_type: Optional[TaskType] = None,
    customer_address: Optional[str] = None,
) -> Dict[str, Any]:
    """Notify central agent. Pass order_id when available (from get_order_for_product) for better context."""
    try:
        full_msg = message
        if order_id:
            full_msg = f"[Order ID: {order_id}] {message}"
        us = await get_user_state(ctx.deps.user_id, ctx.deps.business_id) or {}
        pid = await ensure_central_process(
            us,
            task_type=task_type or TaskType.LOGISTICS_COORDINATION,
            customer_id=ctx.deps.user_id,
            vendor_id=ctx.deps.business_id,
            product_name=ctx.deps.product_name or "",
            order_id=order_id,
            process_id=process_id,
        )
        proc = us.get("processes", {}).get(pid) or {}
        addr = customer_address
        if not addr and isinstance(us, dict):
            addr = us.get("customer_address")
        pname_res = (ctx.deps.product_name or proc.get("product_name") or "").strip()
        try:
            qty = int(proc.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
        try:
            unit = float(proc.get("price") or 0)
        except (TypeError, ValueError):
            unit = 0.0
        line_price = unit * qty
        agent_input = await create_structured_input(
            sender=EntityType.AGENT,
            recipient=coerce_entity(recipient),
            message=full_msg,
            customer=Customer(id=ctx.deps.user_id, address=addr),
            business=Vendor(id=ctx.deps.business_id),
            order_id=order_id,
            product=Product(id="", name=pname_res, quantity=qty, price=line_price)
            if pname_res
            else None,
            process_id=pid,
            task_type=task_type or TaskType.LOGISTICS_COORDINATION,
        )
        await run_central_agent(
            event_message=agent_input,
            user_state=us,
            caller_agent="logistics_agent",
        )
        return {"status": "sent", "message": "Request sent. Customer will be updated when we receive a response from the vendor."}
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
    customer_address: Optional[str] = None,
    append_chat_history: bool = True,
    instructions: Optional[str] = None,
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

    customer_address = customer_address or user_state.get("customer_address")
    if customer_address:
        customer_message = f"Customer address\n{customer_address}\n\nCustomer message:{customer_message}\n\n"
    products_cache = user_state.get("products", {})
    processes = user_state.get("processes", {})
    order_id = kwargs.get("order_id")
    process_id = kwargs.get("process_id")
    pid_s = (str(process_id).strip() if process_id else "") or None
    if not order_id and pid_s:
        pr = (processes or {}).get(pid_s)
        if isinstance(pr, dict) and pr.get("order_id"):
            order_id = str(pr.get("order_id")).strip()
    if (not product_name or not str(product_name).strip()) and pid_s:
        pr = (processes or {}).get(pid_s)
        if isinstance(pr, dict) and pr.get("product_name"):
            product_name = str(pr.get("product_name") or "").strip()
    product_context = f"\nProduct for delivery: {product_name}" if product_name else ""
    order_ctx = f"\nProduct Order ID: {order_id}" if order_id else ""
    process_ctx = f"\nProcess ID: {pid_s}" if pid_s else ""

    deps = LogisticsDeps(
        user_id=user_id,
        business_id=business_id,
        product_name=product_name,
        products_cache=products_cache,
        processes=processes,
        process_id=pid_s,
        resolved_order_id=(str(order_id).strip() if order_id else None) or None,
    )

    run_kw: Dict[str, Any] = {}
    if instructions and instructions.strip():
        run_kw["instructions"] = instructions.strip()
    result = await logistics_agent.run(
        (product_context + process_ctx + order_ctx + customer_message), deps=deps, message_history=user_state.get("chat_history", []), **run_kw
    )
    response = result.output

    if append_chat_history:
        user_state.setdefault("chat_history", []).extend([
            ModelRequest(parts=[UserPromptPart(content=customer_message)]),
            ModelResponse(parts=[TextPart(content=response)]),
        ])

    await save_user_state(user_id, business_id, user_state)

    return response
