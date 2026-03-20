"""
Routing Agent - Determines which agent to use based on conversation context
"""
from typing import Optional, Literal
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from .base_agent import BaseAgent


class ConversationStage(BaseModel):
    """Conversation stage determination"""
    stage: Literal[
        "Product Enquiry",
        "Product purchase",
        "Payment verification",
        "Logistics",
        "Ads Marketing",
        "Customer complaint/Feedback",
        "General"
    ]
    product_name: Optional[str] = None
    product_category: Optional[str] = None
    order_id: Optional[str] = None
    intent: Optional[Literal["enquiry", "purchase"]] = None
    response: Optional[str] = Field(default=None, description="Response if stage is General. None otherwise.")
    confidence: float = 0.0


class RoutingAgentDeps(BaseModel):
    """Dependencies for routing agent"""
    business_id: str
    user_id: str
    business_name: Optional[str] = None
    order_context: Optional[str] = None


# Initialize routing agent
routing_agent_base = BaseAgent(
    system_prompt="""You are a conversation and routing agent for a specific business. Analyze customer messages and determine:
1. The conversation stage: Product Enquiry, Product purchase, Payment verification, Logistics, Ads Marketing, Customer complaint/Feedback, or General
2. Product name if mentioned (default="None")
3. Product category if identifiable
4. Customer intent (enquiry or purchase)
5. Confidence level (0.0 to 1.0)
If the stage is General (i.e pleasantries, introductions, small talk, etc), provide a response to the customer's message.

You are assisting the business. Use the business context to tailor your understanding. Be accurate and concise.""",
    deps_type=RoutingAgentDeps,
    output_type=ConversationStage
)

routing_agent = routing_agent_base.agent


async def route_conversation(
    message: str,
    chat_history: list,
    business_id: str,
    user_id: str,
    business_name: Optional[str] = None,
    order_context: Optional[str] = None,
) -> ConversationStage:
    """Route conversation. Pass order_context (e.g. 'Product A -> order_id_1') for order-aware routing."""
    deps = RoutingAgentDeps(
        business_id=business_id,
        user_id=user_id,
        business_name=business_name,
        order_context=order_context,
    )
    context = f"Business: {business_name}" if business_name else ""
    if order_context:
        context += f"\nOngoing orders (product -> order_id): {order_context}"
    prompt = f"""{context}

Current user message: {message} """

# Determine the conversation stage, provide a respon and extract relevant information (product_name, order_id when applicable)."""
    
    result = await routing_agent.run(prompt, deps=deps, message_history=chat_history)
    return result.output


def format_history(chat_history: list) -> str:
    """Format chat history for prompt"""
    if not chat_history:
        return ""
    
    formatted = []
    for msg in chat_history[-5:]:  # Last 5 messages
        role = msg.get("role", "user")
        content = msg.get("content", "")
        formatted.append(f"{role}: {content}")
    
    return "\n".join(formatted)

