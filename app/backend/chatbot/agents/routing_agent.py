"""
Routing Agent - Determines which agent to use based on conversation context
"""
from typing import Optional, Literal
from pydantic import BaseModel
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
        "Customer support",
        "General"
    ]
    product_name: Optional[str] = None
    product_category: Optional[str] = None
    intent: Optional[Literal["enquiry", "purchase"]] = None
    confidence: float = 0.0


class RoutingAgentDeps(BaseModel):
    """Dependencies for routing agent"""
    business_id: str
    user_id: str


# Initialize routing agent
routing_agent_base = BaseAgent(
    system_prompt="""You are a conversation routing agent. Analyze customer messages and determine:
1. The conversation stage (Product Enquiry, Product purchase, Payment verification, Logistics, Ads Marketing, Customer complaint/Feedback, or General)
2. Product name if mentioned (default="None")
3. Product category if identifiable
4. Customer intent (enquiry or purchase)
5. Confidence level (0.0 to 1.0)

Be accurate and concise.""",
    deps_type=RoutingAgentDeps,
    output_type=ConversationStage
)

routing_agent = routing_agent_base.agent


async def route_conversation(
    message: str,
    chat_history: list,
    business_id: str,
    user_id: str
) -> ConversationStage:
    """
    Route conversation to determine which agent to use.
    
    Args:
        message: Customer message
        chat_history: Previous chat history
        business_id: Business ID
        user_id: User ID
        
    Returns:
        ConversationStage with routing information
    """
    deps = RoutingAgentDeps(business_id=business_id, user_id=user_id)
    
    prompt = f"""current user message: {message}

Determine the conversation stage and extract relevant information."""
    
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

