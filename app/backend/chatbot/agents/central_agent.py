"""
Central Agent - Handles 2-3 way communication between customer, vendor, and logistics
Converted to Pydantic AI with intelligent reasoning and planning
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

import aiofiles
from pydantic import BaseModel, Field, ValidationError
from pydantic_ai import RunContext

from backend.chatbot.agents.central_agent_utils import (
    Customer,
    Logistics,
    Product,
    Vendor,
)
from backend.db.cache_utils import get_user_state
from backend.struct import CentralAgentInput
from backend.whatsapp.utils import whatsapp

from .base_agent import BaseAgent


class CentralAgentResponse(BaseModel):
    """Structured response from central agent"""

    reasoning: str = Field(..., description="Think about what should be done next")
    next_step: str = Field(
        ..., description="Determine your next step and to whom it should be directed"
    )
    message: str = Field(..., description="Message to send")
    recipient: Union[
        Literal["ProductAgent", "PaymentAgent", "LogsiticAgent"],
        Literal["Customer", "Vendor", "Logistics"],
    ] = Field(..., description="Message recipient")
    sender: Union[
        Literal["ProductAgent", "PaymentAgent", "LogsiticAgent"],
        Literal["Customer", "Vendor", "Logistics"],
    ] = Field(..., description="Message sender")


class CentralAgentDeps(BaseModel):
    """Process model for central agent"""

    communication_history: List[Dict[str, Any]] = []
    finished_tasks: Optional[List[str]] = None
    customer: Optional[Customer] = None
    vendor: Optional[Vendor] = None
    product: Optional[Product] = None
    logistics: Optional[Logistics] = None
    id: str


# Initialize central agent with structured output
central_agent_base = BaseAgent(
    system_prompt="""You are a central intelligence agent for automating business operations.

**YOUR JOB**
Coordinate seamless communication between agents, customers, vendors, and logistics companies.
Plan and execute the next steps to achieve seamless purchase and delivery.

**OBJECTIVES**
1. **Logistics Planning**: Coordinate delivery arrangements, collect addresses, track orders
2. **Payment Verification**: Verify customer payments with vendors
3. **Customer Feedback**: Handle complaints and escalate when needed
4. **Product Unavailable**: Confirm availability with vendors and relay to customers

**REASONING PROCESS**
1. Analyze the current situation
2. Determine who needs to be contacted next
3. Decide what information is needed
4. Plan the next communication step
5. Execute and track progress until objective is complete

**RULES**
- Always think step-by-step before responding
- Determine the most appropriate recipient for each message
- Track progress and mark finished when objective is complete
- Be concise and action-oriented""",
    deps_type=CentralAgentDeps,
    output_type=CentralAgentResponse,
)

central_agent = central_agent_base.agent


@central_agent.tool
async def get_order_info(
    ctx: RunContext[CentralAgentDeps], order_id: Optional[str] = None
) -> Dict[str, Any]:
    """Get order information"""
    # TODO: Implement order lookup from database
    return {
        "order_id": order_id or "unknown",
        "status": "pending",
        "product": ctx.deps.product_name,
    }


@central_agent.tool
async def get_delivery_address(ctx: RunContext[CentralAgentDeps]) -> Optional[str]:
    """Get customer delivery address from user state"""
    user_state = await get_user_state(ctx.deps.customer_id, ctx.deps.business_id)
    if user_state:
        processes = user_state.get("processes", {})
        logistics_process = processes.get("Logistic planning", {})
        if logistics_process:
            product_process = logistics_process.get(ctx.deps.product_name, {})
            return product_process.get("customer_address")
    return None


@central_agent.tool
async def get_logistics_info(ctx: RunContext[CentralAgentDeps]) -> Dict[str, Any]:
    """Get logistics company information"""
    # TODO: Implement logistics lookup
    return {
        "logistic_id": ctx.deps.logistic_id or "none",
        "name": "Logistics Company",
        "contact": "contact@logistics.com",
    }


async def get_or_create_user_state(
    customer_id: str, business_id: str, state_dir=Path("./states")
) -> CentralAgentDeps:
    state_key = (
        f"autobiz_{customer_id.replace('-', '_')}_{business_id.replace('-', '_')}"
    )
    state_dir.mkdir(parents=True, exist_ok=True)

    state_file = state_dir / state_key

    if state_file.exists():
        try:
            async with aiofiles.open(state_file, "r") as _file:
                content = await _file.read()
                state = CentralAgentDeps.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError):
            state = CentralAgentDeps(id=state_key)
    else:
        state = CentralAgentDeps(id=state_key)
        async with aiofiles.open(state_file, "w") as f:
            await f.write(json.dumps(state.model_dump(), indent=2))

    return state


async def run_central_agent(
    event_message: CentralAgentInput,
    user_state: Optional[CentralAgentDeps] = None,
    vendor_only: bool = False,
    debug: bool = False,
) -> Dict[str, Any]:
    """
    Run central agent to coordinate multi-party communication.

    Args:
        event_message: Central agent input message
        user_state: Optional user state
        vendor_only: If only vendor/logistics involved
        debug: Debug mode

    Returns:
        Response dictionary
    """
    customer_id = getattr(event_message.customer, "id", "")
    business_id = getattr(event_message.business, "id", "")

    if user_state is None:
        user_state = await get_or_create_user_state(customer_id, business_id)

    if debug:
        print(
            f"Central agent - user_state: {getattr(user_state, 'communication_history', [])}"
        )

    user_state.customer = event_message.customer
    user_state.vendor = event_message.business
    user_state.logistics = event_message.logistic

    # Add current message to communication history
    user_state.communication_history.append(
        {"role": "user", "name": event_message.sender, "content": event_message.message}
    )

    # Run agent
    result = await central_agent.run(
        event_message.message,
        deps=user_state,
    )
    response = result.output

    # Add agent response to communication history
    user_state.communication_history.append(
        {"role": "assistant", "name": response.sender, "content": response.message}
    )

    # Update user state chat history if recipient is customer
    if response.recipient == "Customer":
        user_state.communication_history.append(
            {"role": "assistant", "name": response.sender, "content": response.message}
        )

    # Send WhatsApp message if configured
    try:
        sender_number = get_contact(response.sender, event_message)
        recipient_number = get_contact(response.recipient, event_message)
        if sender_number and recipient_number:
            whatsapp.send_message(sender_number, recipient_number, response.message)
    except Exception as e:
        if debug:
            print(f"WhatsApp send error: {e}")

    return {
        "message": response.message,
        "sender": response.sender,
        "recipient": response.recipient,
        "finished": response.finished,
        "reasoning": response.reasoning,
    }


def get_contact(entity: str, event_message: CentralAgentInput) -> Optional[str]:
    """Get contact ID for entity"""
    entity_lower = entity.lower()
    if entity_lower == "customer":
        return getattr(event_message.customer, "id")
    elif entity_lower == "vendor":
        return getattr(event_message.business, "id")
    elif entity_lower == "logistics":
        return getattr(event_message.logistic, "id")
    return None
