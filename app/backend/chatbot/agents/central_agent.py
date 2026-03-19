"""
Central Agent - Handles 2-3 way communication between customer, vendor, and logistics.
Creates orders on payment confirmation. Tracks finished tasks.
"""

import json
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from backend.chatbot.agents.central_agent_utils import Customer, Logistics, Product, Vendor
from backend.db.cache_utils import get_user_state, modify_user_state, push_to_inbox
from backend.db.db_utils import (
    create_order as db_create_order,
    get_business_info,
    get_logistics_companies,
    get_order_by_id,
    get_order_by_number,
    get_orders_by_user,
    get_user_by_id,
    update_order_status as db_update_order_status,
)
from backend.struct import CentralAgentInput
from backend.whatsapp.utils import whatsapp
from pydantic_ai import RunContext

from .base_agent import BaseAgent


class CentralAgentResponse(BaseModel):
    """Structured response from central agent"""

    reasoning: str = Field(..., description="Think about what should be done next")
    next_step: str = Field(
        ..., description="Determine your next step and to whom it should be directed"
    )
    message: str = Field(..., description="Message to send")
    recipient: Union[
        Literal["ProductAgent", "PaymentAgent", "LogisticAgent"],
        Literal["Customer", "Vendor", "Logistics"],
    ] = Field(..., description="Message recipient")
    sender: Union[
        Literal["ProductAgent", "PaymentAgent", "LogisticAgent"],
        Literal["Customer", "Vendor", "Logistics"],
    ] = Field(..., description="Message sender")


class CentralAgentDeps(BaseModel):
    """Dependencies for central agent. Uses Redis state for processes and finished_tasks."""

    communication_history: List[Dict[str, Any]] = []
    finished_tasks: List[str] = []
    customer: Optional[Customer] = None
    vendor: Optional[Vendor] = None
    product: Optional[Product] = None
    logistics: Optional[Logistics] = None
    customer_id: str = ""
    business_id: str = ""
    logistic_id: Optional[str] = None
    product_name: Optional[str] = None
    order_id: Optional[str] = None
    id: str = ""


class EntityType(str, Enum):
    CUSTOMER = "Customer"
    VENDOR = "Vendor"
    LOGISTICS = "Logistics"


central_agent_base = BaseAgent(
    system_prompt="""You are a central intelligence agent for automating business operations.

**YOUR JOB**
Coordinate communication between customers, vendors, and logistics. Confirm payment (verbal or via payment link). Create orders in DB once payment is confirmed. Track completed tasks in finished_tasks.

**OBJECTIVES**
1. **Payment confirmation**: Confirm via vendor/logistics verbal reply or payment link verification. Create order in DB when confirmed.
2. **Logistics**: Coordinate delivery, collect addresses, track orders. Use order_id from processes when available.
3. **Customer feedback**: Handle complaints and escalate when needed.
4. **Product unavailable**: Confirm availability with vendors and relay to customers.

**TOOLS**
- create_order: Call when payment is confirmed (by vendor or payment link). Creates order in DB and caches in processes.
- get_order_info: Read order from DB or processes cache.
- update_order_status: Update order status (shipped, delivered, cancelled). Call when vendor/logistics confirms delivery.
- mark_task_finished: Add completed activity to finished_tasks. Call when payment confirmed, order created, delivery arranged, etc.
- get_delivery_address, get_logistics_info, get_contact_info: Fetch context for coordination.

**RULES**
- Create order only after payment confirmation. Update finished_tasks when tasks complete.
- Use order_id from incoming messages when logistics/vendor provide it.
- Be concise and action-oriented.""",
    deps_type=CentralAgentDeps,
    output_type=CentralAgentResponse,
)

central_agent = central_agent_base.agent


def _customer_id(ctx: RunContext[CentralAgentDeps]) -> str:
    return ctx.deps.customer_id or (ctx.deps.customer.id if ctx.deps.customer else "")


def _business_id(ctx: RunContext[CentralAgentDeps]) -> str:
    return ctx.deps.business_id or (ctx.deps.vendor.id if ctx.deps.vendor else "")


@central_agent.tool
async def create_order(
    ctx: RunContext[CentralAgentDeps],
    product_name: str,
    total_amount: float,
    delivery_address: Optional[str] = None,
    delivery_city: Optional[str] = None,
    delivery_state: Optional[str] = None,
) -> Dict[str, Any]:
    """Create order in DB and cache in Redis processes. Call only after payment is confirmed."""
    customer_id = _customer_id(ctx)
    business_id = _business_id(ctx)
    if not customer_id or not business_id:
        return {"error": "Missing customer or business context"}

    try:
        order = await db_create_order(
            user_id=customer_id,
            business_id=business_id,
            total_amount=total_amount,
            delivery_address=delivery_address,
            delivery_city=delivery_city,
            delivery_state=delivery_state,
            metadata={"product_name": product_name},
        )
        order_id = str(order["id"])
        order_number = order["order_number"]

        user_state = await get_user_state(customer_id, business_id) or {}
        processes = user_state.get("processes", {})
        if product_name not in processes:
            processes[product_name] = {}
        processes[product_name].update({
            "order_id": order_id,
            "order_number": order_number,
            "customer_address": delivery_address,
            "status": "pending",
        })
        user_state["processes"] = processes
        await modify_user_state(customer_id, business_id, user_state)

        return {
            "order_id": order_id,
            "order_number": order_number,
            "status": "created",
            "message": f"Order {order_number} created for {product_name}",
        }
    except Exception as e:
        return {"error": str(e)}


@central_agent.tool
async def get_order_info(
    ctx: RunContext[CentralAgentDeps],
    order_id: Optional[str] = None,
    order_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Get order from DB or processes cache. Pass order_id or order_number."""
    customer_id = _customer_id(ctx)
    business_id = _business_id(ctx)
    user_state = await get_user_state(customer_id, business_id) or {}

    if order_id:
        order = await get_order_by_id(order_id)
        if order:
            return dict(order)
    if order_number:
        order = await get_order_by_number(order_number)
        if order:
            return dict(order)

    processes = user_state.get("processes", {})
    for pname, proc in processes.items():
        if proc.get("order_id") == order_id or proc.get("order_number") == order_number:
            return {"product_name": pname, **proc}
        if not order_id and not order_number and proc.get("order_id"):
            return {"product_name": pname, **proc}

    return {"error": "Order not found"}


@central_agent.tool
async def update_order_status(
    ctx: RunContext[CentralAgentDeps],
    order_id: str,
    status: str,
    tracking_number: Optional[str] = None,
    logistic_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Update order status in DB. Status: pending, payment_verified, shipped, delivered, cancelled. Call when vendor/logistics confirms delivery or shipping."""
    try:
        updated = await db_update_order_status(
            order_id=order_id,
            status=status,
            tracking_number=tracking_number or "",
            logistic_id=logistic_id or "",
        )
        if not updated:
            return {"error": "Order not found", "order_id": order_id}
        customer_id = _customer_id(ctx)
        business_id = _business_id(ctx)
        user_state = await get_user_state(customer_id, business_id) or {}
        processes = user_state.get("processes", {})
        for pname, proc in processes.items():
            if proc.get("order_id") == order_id:
                processes[pname]["status"] = status
                if tracking_number:
                    processes[pname]["tracking_number"] = tracking_number
                break
        user_state["processes"] = processes
        await modify_user_state(customer_id, business_id, user_state)
        return {"status": "updated", "order_id": order_id, "new_status": status}
    except Exception as e:
        return {"error": str(e)}


@central_agent.tool
async def mark_task_finished(
    ctx: RunContext[CentralAgentDeps],
    task_description: str,
) -> Dict[str, Any]:
    """Add completed activity to finished_tasks. E.g. 'Payment verified for Product X', 'Order ORD-xxx created'."""
    finished = ctx.deps.finished_tasks
    if task_description not in finished:
        finished.append(task_description)
    return {"status": "updated", "finished_tasks": finished}


@central_agent.tool
async def get_delivery_address(
    ctx: RunContext[CentralAgentDeps],
    product_name: Optional[str] = None,
) -> Optional[str]:
    """Get customer delivery address from processes. Pass product_name if known."""
    customer_id = _customer_id(ctx)
    business_id = _business_id(ctx)
    user_state = await get_user_state(customer_id, business_id) or {}
    processes = user_state.get("processes", {})

    pname = product_name or ctx.deps.product_name
    if pname and pname in processes:
        return processes[pname].get("customer_address")

    user_info = await get_user_by_id(customer_id)
    if user_info:
        return user_info.get("delivery_address")
    return None


@central_agent.tool
async def get_logistics_info(ctx: RunContext[CentralAgentDeps]) -> Dict[str, Any]:
    """Get logistics companies for the vendor. Returns list of available logistics."""
    try:
        logistics = await get_logistics_companies(limit=5)
        if logistics:
            return {"logistics": [{"id": str(l["id"]), "name": l["name"], "phone": l.get("phone_number")} for l in logistics]}
        return {"logistics": [], "message": "No logistics companies configured"}
    except Exception as e:
        return {"error": str(e)}


@central_agent.tool
async def get_contact_info(
    ctx: RunContext[CentralAgentDeps],
    entity: EntityType,
) -> Dict[str, Any]:
    """Get contact info for Customer, Vendor, or Logistics."""
    try:
        if entity == EntityType.CUSTOMER:
            uid = _customer_id(ctx)
            info = await get_user_by_id(uid) if uid else None
            if info:
                return {"phone": info.get("phone_number"), "name": info.get("full_name"), "address": info.get("delivery_address")}
        elif entity == EntityType.VENDOR:
            bid = _business_id(ctx)
            info = await get_business_info(bid) if bid else None
            if info:
                return {"phone": info.get("phone_number"), "email": info.get("email"), "name": info.get("name")}
        elif entity == EntityType.LOGISTICS:
            if ctx.deps.logistics:
                return {"id": ctx.deps.logistics.id, "name": ctx.deps.logistics.name, "phone": ctx.deps.logistics.phone}
            lid = ctx.deps.logistic_id
            if lid:
                info = await get_business_info(lid)
                if info:
                    return {"id": str(info.get("id")), "name": info.get("name"), "phone": info.get("phone_number")}
        return {}
    except Exception as e:
        return {"error": str(e)}


async def run_central_agent(
    event_message: CentralAgentInput,
    user_state: Optional[Dict[str, Any]] = None,
    vendor_only: bool = False,
    debug: bool = False,
) -> Dict[str, Any]:
    """Run central agent. Uses Redis state. Builds CentralAgentDeps from event + Redis."""
    customer_id = getattr(event_message.customer, "id", "") if event_message.customer else ""
    business_id = getattr(event_message.business, "id", "") if event_message.business else ""

    redis_state = user_state or await get_user_state(customer_id, business_id) or {}
    redis_state = redis_state if isinstance(redis_state, dict) else {}

    finished_tasks = redis_state.get("finished_tasks", [])
    if not isinstance(finished_tasks, list):
        finished_tasks = []

    comm_history = redis_state.get("central_communication_history", [])
    if not isinstance(comm_history, list):
        comm_history = []

    product_name = None
    if event_message.product:
        product_name = event_message.product.name

    deps = CentralAgentDeps(
        communication_history=comm_history,
        finished_tasks=finished_tasks,
        customer=event_message.customer,
        vendor=event_message.business,
        product=event_message.product,
        logistics=event_message.logistic,
        customer_id=customer_id,
        business_id=business_id,
        logistic_id=getattr(event_message.logistic, "id", None) if event_message.logistic else None,
        product_name=product_name,
        order_id=event_message.order_id,
        id=f"{customer_id}:{business_id}",
    )

    comm_history.append(
        {"role": "user", "name": event_message.sender, "content": event_message.message}
    )

    result = await central_agent.run(
        f"Context: {json.dumps(comm_history[-10:])}",
        deps=deps,
    )
    response = result.output

    comm_history.append(
        {"role": "assistant", "name": response.sender, "content": response.message}
    )

    finished_tasks = deps.finished_tasks or finished_tasks
    redis_state["central_communication_history"] = comm_history[-50:]
    redis_state["finished_tasks"] = finished_tasks
    await modify_user_state(customer_id, business_id, redis_state)

    recipient_lower = response.recipient.lower()
    recipient_id = None
    if recipient_lower == "vendor":
        recipient_id = business_id
    elif recipient_lower == "logistics" and event_message.logistic:
        recipient_id = getattr(event_message.logistic, "id", None)
    elif recipient_lower == "customer":
        recipient_id = customer_id

    if recipient_id:
        inbox_payload = {
            "message": response.message,
            "sender": response.sender,
            "recipient": response.recipient,
        }
        if customer_id and recipient_lower in ("vendor", "logistics"):
            inbox_payload["customer_id"] = customer_id
        if product_name:
            inbox_payload["product_name"] = product_name
        if event_message.order_id:
            inbox_payload["order_id"] = event_message.order_id
        if recipient_lower == "customer" and business_id:
            inbox_payload["business_id"] = business_id
        await push_to_inbox(recipient_id, inbox_payload)

    try:
        sender_num = get_contact(response.sender, event_message)
        recipient_num = get_contact(response.recipient, event_message)
        if sender_num and recipient_num:
            whatsapp.send_message(sender_num, recipient_num, response.message)
    except Exception as e:
        if debug:
            print(f"WhatsApp send error: {e}")

    return {
        "message": response.message,
        "sender": response.sender,
        "recipient": response.recipient,
        "reasoning": response.reasoning,
    }


def get_contact(entity: str, event_message: CentralAgentInput) -> Optional[str]:
    """Get contact ID for entity (phone or id for WhatsApp)."""
    entity_lower = entity.lower()
    if entity_lower == "customer" and event_message.customer:
        return getattr(event_message.customer, "phone", None) or getattr(event_message.customer, "id", None)
    if entity_lower == "vendor" and event_message.business:
        return getattr(event_message.business, "phone", None) or getattr(event_message.business, "id", None)
    if entity_lower == "logistics" and event_message.logistic:
        return getattr(event_message.logistic, "phone", None) or getattr(event_message.logistic, "id", None)
    return None
