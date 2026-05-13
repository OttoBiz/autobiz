"""
Customer Complaint Agent - Handles customer complaints and feedback
Converted to pydantic_ai
"""

from typing import Any, Dict, Optional

from fastapi import BackgroundTasks
from pydantic import BaseModel
from pydantic_ai import RunContext

from backend.chatbot.agents.central_agent_utils import (
    coerce_entity,
    create_structured_input,
    ensure_central_process,
)
from backend.chatbot.utils.agent_utils import (
    format_handoff_process_context,
    get_or_create_user_state,
    get_process_snapshot,
    save_user_state,
)
from backend.db.cache_utils import get_user_state, modify_user_state
from backend.struct import Customer, EntityType, Product, TaskType, Vendor

from .base_agent import BaseAgent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

class CustomerComplaintDeps(BaseModel):
    """Dependencies for customer complaint agent"""

    user_id: str
    business_id: str
    product_name: Optional[str] = None
    process_id: Optional[str] = None


# Initialize customer complaint agent
customer_complaint_agent_base = BaseAgent(
    system_prompt="""You are the **complaints specialist**: empathetic, fair, de-escalation first.

**Workflow**
1. Acknowledge the customer's frustration. Restate the issue to confirm understanding.
2. Propose a concrete next step within policy (exchange, refund timeline, investigation).
3. If the issue requires vendor/logistics action (refunds, chargebacks, defective items, returns), call `notify_central_agent` to escalate with a clear summary.

**Rules**
- Never be defensive. Short apologies where appropriate; give clear timelines.
- Do not promise refunds or replacements you cannot authorize — escalate instead.""",
    deps_type=CustomerComplaintDeps,
)

customer_complaint_agent = customer_complaint_agent_base.agent


@customer_complaint_agent.tool
async def notify_central_agent(
    ctx: RunContext[CustomerComplaintDeps],
    message: str,
    recipient: str = "Vendor",
    product_name: str = "",
    process_id: Optional[str] = None,
    task_type: Optional[TaskType] = None,
) -> Dict[str, Any]:
    """Escalate complaint to vendor or logistics via the central agent."""
    try:
        from backend.chatbot.agents.central_agent import run_central_agent

        pname = product_name or ctx.deps.product_name or ""
        us = await get_user_state(ctx.deps.user_id, ctx.deps.business_id) or {}
        pid = await ensure_central_process(
            us,
            task_type=task_type or TaskType.COMPLAINT,
            customer_id=ctx.deps.user_id,
            vendor_id=ctx.deps.business_id,
            product_name=pname,
            process_id=process_id or ctx.deps.process_id,
        )
        agent_input = await create_structured_input(
            sender=EntityType.AGENT,
            recipient=coerce_entity(recipient),
            message=message,
            customer=Customer(id=ctx.deps.user_id),
            business=Vendor(id=ctx.deps.business_id),
            product=Product(id="", name=pname, quantity=1, price=0.0) if pname else None,
            process_id=pid,
            task_type=TaskType.COMPLAINT,
        )
        await run_central_agent(
            event_message=agent_input,
            user_state=us,
            caller_agent="customer_complaint_agent.notify_central_agent",
        )
        return {"status": "sent", "message": "Complaint escalated. Customer will be updated when we receive a response."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def run_customer_complaint_agent(
    customer_message: str,
    product_name: str,
    user_id: str,
    business_id: str,
    user_state: Optional[Dict[str, Any]] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    debug: bool = False,
    append_chat_history: bool = True,
    instructions: Optional[str] = None,
    process_id: Optional[str] = None,
    **kwargs,
) -> tuple[str, Dict[str, Any]]:
    """
    Run customer complaint agent.

    Args:
        complaint: Customer complaint message
        product_name: Product name related to complaint
        user_id: User ID
        business_id: Business ID
        user_state: Optional user state
        background_tasks: Background tasks
        debug: Debug mode

    Returns:
        Tuple of (response_message, updated_user_state)
    """
    if not user_state:
        user_state = await get_or_create_user_state(user_id, business_id)

    proc = get_process_snapshot(user_state, process_id)
    if proc and (not product_name or not str(product_name).strip()) and proc.get("product_name"):
        product_name = str(proc.get("product_name") or "").strip()

    deps = CustomerComplaintDeps(
        user_id=user_id,
        business_id=business_id,
        product_name=product_name or "",
        process_id=(process_id or "").strip() or None,
    )

    product_ctx = f"\nProduct: {product_name}" if product_name else ""
    proc_line = ""
    if proc and (process_id or "").strip():
        proc_line = "\n" + format_handoff_process_context(str(process_id).strip(), proc)
    prompt = f"Customer complaint: {customer_message}{product_ctx}{proc_line}"
    run_kw: Dict[str, Any] = {}
    if instructions and instructions.strip():
        run_kw["instructions"] = instructions.strip()
    result = await customer_complaint_agent.run(prompt, deps=deps, **run_kw)
    response = result.output

    if append_chat_history:
        user_state.setdefault("chat_history", []).extend([
            ModelRequest(parts=[UserPromptPart(content=customer_message)]),
            ModelResponse(parts=[TextPart(content=response)]),
        ])

    await save_user_state(user_id, business_id, user_state)

    return response, user_state
