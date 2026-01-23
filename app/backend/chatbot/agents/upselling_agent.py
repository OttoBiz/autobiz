"""
Upselling Agent - Recommends complementary and alternative products
Converted to pydantic_ai
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from .base_agent import BaseAgent
from backend.modules.products import search_products, get_product_images
from backend.modules.services import search_services
from backend.db.db_utils import get_products
from backend.config import config


class UpsellingAgentDeps(BaseModel):
    """Dependencies for upselling agent"""
    business_id: str
    api_key: Optional[str] = None


# Initialize upselling agent
upselling_agent_base = BaseAgent(
    system_prompt="""You're an AI upselling and marketing agent.

**OBJECTIVE**
- Upsell and drive sales of similar or complementary products to customers.

**MODE OF OPERATION**
After a customer's purchase or inquiry:
1. Identify complementary or alternative products.
2. Suggest these items, emphasizing benefits and compatibility.
3. Use persuasive language, but respect customer preferences.
4. Offer bundle deals or discounts when appropriate.
5. Adapt recommendations based on customer responses.
6. Aim to enhance customer's experience and increase sales.
7. Be friendly, knowledgeable, and focused on customer satisfaction.

Keep responses concise and conversational.""",
    deps_type=UpsellingAgentDeps
)

upselling_agent = upselling_agent_base.agent


@upselling_agent.tool
async def get_related_products(
    ctx: RunContext[UpsellingAgentDeps],
    product_name: str,
    category: Optional[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """Get related products from database with multimodal support"""
    products = await search_products(product_name, business_id=ctx.deps.business_id, category=category, limit=limit)
    
    # Add image URLs for multimodal retrieval
    for product in products:
        if product.get("id"):
            images = await get_product_images(product["id"])
            product["image_urls"] = images
    
    return products


@upselling_agent.tool
async def get_cross_sell_products(
    ctx: RunContext[UpsellingAgentDeps],
    product_category: str,
    limit: int = 3
) -> List[Dict[str, Any]]:
    """Get cross-sell products from other businesses (premium feature)"""
    # TODO: Implement cross-selling from other businesses
    products = await search_products("", category=product_category, limit=limit)
    return products


@upselling_agent.tool
async def get_complementary_products(
    ctx: RunContext[UpsellingAgentDeps],
    product_category: str,
    limit: int = 3
) -> List[Dict[str, Any]]:
    """Get complementary products in the same category"""
    products = await get_products(category=product_category)
    return products[:limit]


async def run_upselling_agent(
    product: str,
    intent: str = "inquired",
    conversation_messages: Optional[List] = None,
    business_id: str = None,
    api_key: Optional[str] = None,
    **kwargs
) -> str:
    """
    Run upselling agent to recommend products.
    
    Args:
        product: Product name that was purchased/inquired
        intent: Intent - "purchased" or "inquired"
        conversation_messages: Previous conversation messages
        business_id: Business ID
        api_key: Optional API key
        
    Returns:
        Upselling response message
    """
    deps = UpsellingAgentDeps(
        business_id=business_id or "",
        api_key=api_key
    )
    
    if intent == "purchased":
        instruction = "This item was purchased. Suggest, market and upsell persuasively only the best (at most 2) complementary products that can be used alongside the bought product(s)."
    else:
        instruction = "This item was inquired but not available. Suggest, market and upsell persuasively only the top 2 direct/complete alternative products to buy."
    
    prompt = f"""Product: {product}
Instruction: {instruction}

{format_conversation(conversation_messages) if conversation_messages else ''}

Provide a friendly, persuasive recommendation."""
    
    result = await upselling_agent.run(prompt, deps=deps)
    return result.output


def format_conversation(messages: List) -> str:
    """Format conversation messages for prompt"""
    if not messages:
        return ""
    
    formatted = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        formatted.append(f"{role}: {content}")
    
    return "\n".join(formatted)
