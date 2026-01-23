"""
Central Agent - Handles 2-3 way communication between customer, vendor, and logistics
Converted to Pydantic AI with intelligent reasoning and planning
"""
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from .base_agent import BaseAgent
from .agent_utils import get_or_create_user_state, save_user_state, format_chat_history
from backend.db.cache_utils import get_user_state, modify_user_state
from backend.whatsapp.utils import whatsapp
from backend.struct import CentralAgentInput


class CentralAgentResponse(BaseModel):
    """Structured response from central agent"""
    reasoning: str = Field(..., description="Think about what should be done next")
    next_step: str = Field(..., description="Determine your next step and to whom it should be directed")
    message: str = Field(..., description="Message to send")
    recipient: Literal["Agent", "Customer", "Vendor", "Logistics"] = Field(
        ..., description="Message recipient"
    )
    sender: Literal["Agent", "Customer", "Vendor", "Logistics"] = Field(
        ..., description="Message sender"
    )
    finished: bool = Field(..., description="True if objective achieved, else False")
    product: str = Field(..., description="Product name being handled")


class CentralAgentDeps(BaseModel):
    """Dependencies for central agent"""
    customer_id: str
    business_id: str
    logistic_id: Optional[str] = None
    product_name: str
    price: Optional[str] = None
    message_type: str
    api_key: Optional[str] = None


# Initialize central agent with structured output
central_agent_base = BaseAgent(
    system_prompt="""You are a central intelligence agent for automating business operations.

**YOUR JOB**
Coordinate seamless 3-way communication between customers, vendors, and logistics companies.
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
    output_type=CentralAgentResponse
)

central_agent = central_agent_base.agent


@central_agent.tool
async def get_order_info(
    ctx: RunContext[CentralAgentDeps],
    order_id: Optional[str] = None
) -> Dict[str, Any]:
    """Get order information"""
    # TODO: Implement order lookup from database
    return {
        "order_id": order_id or "unknown",
        "status": "pending",
        "product": ctx.deps.product_name
    }


@central_agent.tool
async def get_delivery_address(
    ctx: RunContext[CentralAgentDeps]
) -> Optional[str]:
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
async def get_logistics_info(
    ctx: RunContext[CentralAgentDeps]
) -> Dict[str, Any]:
    """Get logistics company information"""
    # TODO: Implement logistics lookup
    return {
        "logistic_id": ctx.deps.logistic_id or "none",
        "name": "Logistics Company",
        "contact": "contact@logistics.com"
    }


async def run_central_agent(
    event_message: CentralAgentInput,
    user_state: Optional[Dict[str, Any]] = None,
    vendor_only: bool = False,
    debug: bool = False
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
    customer_id = event_message.customer_id or ""
    business_id = event_message.business_id or ""
        
    if user_state is None:
        user_state = await get_or_create_user_state(customer_id, business_id)
        
    if debug:
        print(f"Central agent - user_state: {user_state.get('chat_history', [])}")
    
    # Get or create process
    processes = user_state.get("processes", {})
    message_type = event_message.message_type or "Logistic planning"
    product_name = event_message.product_name or "unknown"
    
    # Get or create process for this message type and product
    if message_type not in processes:
        processes[message_type] = {}
    
    if product_name not in processes[message_type]:
        processes[message_type][product_name] = {
            "communication_history": [],
            "task_type": message_type,
            "price": event_message.price or "",
            "customer_address": event_message.customer_address or "",
            "logistic_id": event_message.logistic_id or ""
        }
    
    process = processes[message_type][product_name]
    
    # Add current message to communication history
    process["communication_history"].append({
        "role": "user",
        "name": event_message.sender,
        "content": event_message.message
    })
    
    # Prepare prompt with context
    deps = CentralAgentDeps(
        customer_id=customer_id,
        business_id=business_id,
        logistic_id=event_message.logistic_id,
        product_name=product_name,
        price=event_message.price,
        message_type=message_type
    )
    
    # Build comprehensive prompt
    prompt_parts = [
        f"Message Type: {message_type}",
        f"Product: {product_name}",
        f"Price: {event_message.price or 'Not specified'}",
        f"Sender: {event_message.sender}",
        f"Message: {event_message.message}",
    ]
    
    if process.get("customer_address"):
        prompt_parts.append(f"Customer Address: {process['customer_address']}")
    
    if process.get("communication_history"):
        prompt_parts.append(f"\nCommunication History:\n{format_chat_history(process['communication_history'])}")
    
    # Add specific context based on message type
    if message_type == "Payment verification":
        prompt_parts.append("\nVerify payment details and confirm with vendor if needed.")
    elif message_type == "Logistic planning":
        prompt_parts.append("\nCoordinate delivery logistics. Collect address if missing.")
    elif message_type == "Customer Feedback":
        prompt_parts.append("\nHandle complaint. Escalate to human agent if complex.")
    elif message_type == "Product Unavailable":
        prompt_parts.append("\nConfirm product availability with vendor.")
    
    prompt = "\n".join(prompt_parts)
    
    # Run agent
    result = await central_agent.run(prompt, deps=deps)
    response = result.output
    
    # Add agent response to communication history
    process["communication_history"].append({
        "role": "assistant",
        "name": response.sender,
        "content": response.message
    })
    
    # Update user state chat history if recipient is customer
    if response.recipient == "Customer":
        user_state.setdefault("chat_history", []).append({
            "role": "assistant",
            "name": response.sender,
            "content": response.message
        })
    
    # Update process status
    if response.finished:
        # Remove completed process
        if product_name in processes[message_type]:
            del processes[message_type][product_name]
    else:
        # Update process
        processes[message_type][product_name] = process
        
    user_state["processes"] = processes
    
    # Save user state
    if vendor_only:
        await modify_user_state(business_id, business_id, user_state)
    else:
        await modify_user_state(customer_id, business_id, user_state)
    
    if debug:
        print(f"Central agent response: {response}")
        print(f"Finished: {response.finished}")
    
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
        "reasoning": response.reasoning
    }


def get_contact(entity: str, event_message: CentralAgentInput) -> Optional[str]:
    """Get contact ID for entity"""
    entity_lower = entity.lower()
    if entity_lower == "customer":
        return event_message.customer_id
    elif entity_lower == "vendor":
        return event_message.business_id
    elif entity_lower == "logistics":
        return event_message.logistic_id
    return None
