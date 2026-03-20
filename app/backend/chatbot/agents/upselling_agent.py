"""
Upselling Agent - Recommends complementary and alternative products
Converted to pydantic_ai
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from .base_agent import BaseAgent
from backend.modules.products import get_product_images
from backend.modules.products import search_products
from backend.db.db_utils import get_products


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
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Get cross-sell products from other businesses (excludes current vendor)."""
    products = await get_products(
        category=product_category,
        exclude_business_id=ctx.deps.business_id or None,
        limit=limit,
    )
    for p in products:
        if p.get("id"):
            images = await get_product_images(p["id"])
            p["image_urls"] = images
    return products


@upselling_agent.tool
async def get_complementary_products(
    ctx: RunContext[UpsellingAgentDeps],
    product_category: str,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Get complementary products in the same category from this business."""
    products = await get_products(
        business_id=ctx.deps.business_id or None,
        category=product_category,
        limit=limit,
    )
    return products


async def run_ads_marketing_agent(
    customer_message: str,
    product_name: Optional[str] = None,
    business_id: str = None,
    user_state: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> str:
    """Run upselling agent for Ads/Marketing stage. Promotes products and offers."""
    deps = UpsellingAgentDeps(business_id=business_id or "", api_key=kwargs.get("api_key"))
    chat_history = (user_state or {}).get("chat_history", []) if user_state else []
    instruction = "The customer is interested in promotions or marketing. Suggest relevant products, deals, or complementary items from this business. Be persuasive but helpful."
    prompt = f"""Customer message: {customer_message}
Product context: {product_name or "General interest"}

Instruction: {instruction}

{format_conversation(chat_history[-6:]) if chat_history else ""}

Provide a friendly, persuasive marketing response."""
    result = await upselling_agent.run(prompt, deps=deps)
    return result.output


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
    """Format conversation messages for prompt. Handles both dicts and pydantic_ai ModelRequest/ModelResponse."""
    if not messages:
        return ""

    formatted = []
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role", "user")
            content = msg.get("content", "")
        else:
            # pydantic_ai ModelRequest (user) or ModelResponse (assistant)
            role = "user" if getattr(msg, "kind", None) == "request" else "assistant"
            parts = getattr(msg, "parts", [])
            content = " ".join(
                getattr(p, "content", str(p)) for p in parts
            ).strip() if parts else ""
        formatted.append(f"{role}: {content}")

    return "\n".join(formatted)
