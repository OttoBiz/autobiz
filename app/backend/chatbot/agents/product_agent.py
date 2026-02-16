"""
Product Agent - Handles product inquiries and purchases
Converted to pydantic_ai
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from pydantic_ai import RunContext

from backend.chatbot.agents.upselling_agent import run_upselling_agent
from backend.chatbot.utils.agent_utils import get_or_create_user_state, save_user_state
from backend.db.cache_utils import get_user_state
from backend.db.db_utils import get_products
from backend.modules.products import get_product_images, get_products_by_business

from .base_agent import BaseAgent


class ProductInfo(BaseModel):
    """Product information structure"""

    product_name: str
    price: float
    items_in_stock: int
    description: Optional[str] = None
    category: Optional[str] = None


class ProductAgentDeps(BaseModel):
    """Dependencies for product agent"""

    user_id: str
    business_id: str
    chat_history: Optional[List[Any]] = None


# Initialize product agent
product_agent_base = BaseAgent(
    system_prompt="""You are a vendor assistant that:
- Provides relevant information to customer enquiries about products (price, stock availability, product attributes).
- Provides payment details (bank details or payment links) when a customer intends to purchase a product.
- Clarifies or asks about details and specific attributes of products to provide accurate information.
- Matches existing products in the vendor's inventory for the best customer experience.
- If no product matches, upsells other similar or relevant products.

Keep your responses concise. Respond in a chat messaging style.""",
    deps_type=ProductAgentDeps,
)

product_agent = product_agent_base.agent


@product_agent.tool
async def get_product_info(
    ctx: RunContext[ProductAgentDeps], product_name: str, category: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get product information from database with multimodal support"""
    if ctx.deps.business_id:
        products = await get_products_by_business(
            ctx.deps.business_id, category=category
        )
        # Filter by name
        products = [
            p
            for p in products
            if product_name.lower() in p.get("product_name", "").lower()
        ]
    else:
        products = await get_products(name=product_name, category=category)

    # Add image URLs for multimodal retrieval
    for product in products:
        if product.get("id"):
            images = await get_product_images(product["id"])
            product["image_urls"] = images

    return products


@product_agent.tool
async def get_business_payment_info(
    ctx: RunContext[ProductAgentDeps],
) -> Dict[str, str]:
    """Get business payment information"""
    user_state = await get_user_state(ctx.deps.user_id, ctx.deps.business_id)
    business_info = user_state.get("business_information", {})

    return {
        "bank_name": business_info.get("bank_name", ""),
        "bank_account_number": business_info.get("bank_account_number", ""),
        "bank_account_name": business_info.get("bank_account_name", ""),
        "paystack_public_key": business_info.get("paystack_public_key", ""),
    }


# @product_agent.tool
# async def upsell_products(
#     ctx: RunContext[ProductAgentDeps],
#     product_name: str,
#     category: Optional[str] = None,
#     intent: str = "enquiry",
#     **kwargs,
# ) -> List[Dict[str, Any]]:
#     """Upsell products"""
#     return await run_upselling_agent(
#         product_name,
#         intent=intent,
#         conversation_messages=ctx.deps.chat_history,
#         business_id=ctx.deps.business_id,
#         category=category,
#         **kwargs,
#     )


async def run_product_agent(
    customer_message: str,
    product_name: str,
    product_category: str,
    intent: str = "enquiry",
    user_id: str = "",
    business_id: str = "",
    user_state: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    debug: bool = False,
) -> tuple[str, Dict[str, Any]]:
    """
    Run product agent to handle customer product inquiries.

    Args:
        customer_message: Customer's message
        product_name: Name of the product inquired about
        product_category: Category of the product
        intent: Customer intent (enquiry, purchase)
        user_id: User ID
        business_id: Business ID
        user_state: Optional user state (will be fetched if not provided)
        api_key: Optional API key
        debug: Debug mode

    Returns:
        Tuple of (response_message, updated_user_state)
    """
    if not user_state:
        user_state = await get_or_create_user_state(user_id, business_id)

    # Get chat history
    chat_history = user_state.get("chat_history", [])

    # Prepare prompt
    prompt_parts = [f"Customer message: {customer_message}"]

    if product_name.strip() != "NONE":
        # Check if product was already queried
        products_cache = user_state.get("products", {})
        product_cache = products_cache.get(product_name, {})

        if not product_cache.get("db_queried", False):
            # Query database for products
            products = await get_products(name=product_name, category=product_category)
            product_cache = {"retrieved_results": products, "db_queried": True}
            user_state.setdefault("products", {})[product_name] = product_cache

        products = product_cache.get("retrieved_results", [])

        if products:
            products_info = "\n".join(
                [
                    f"- {p.get('product_name', '')}: ${p.get('price', 0)} (Stock: {p.get('items_left_in_stock', 0)})"
                    for p in products[:5]
                ]
            )
            prompt_parts.append(f"\nAvailable products:\n{products_info}")
        else:
            prompt_parts.append(
                "\nNo matching products found in inventory."
            )  ##TODO: Add upsell products

    if intent == "purchase":
        prompt_parts.append("\nCustomer intent: Purchase - provide payment details.")

    # Create dependencies
    deps = ProductAgentDeps(
        user_id=user_id or "",
        business_id=business_id or "",
        chat_history=chat_history,
    )

    # Run agent
    result = await product_agent.run("\n".join(prompt_parts), deps=deps)

    response = result.output

    # Update user state with serializable chat history
    user_state["chat_history"].extend(
        [
            {"role": "user", "content": customer_message},
            {"role": "assistant", "content": response},
        ]
    )

    await save_user_state(user_id, business_id, user_state)

    return response, user_state
