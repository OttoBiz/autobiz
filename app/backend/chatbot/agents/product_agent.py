"""
Product Agent - Handles product inquiries and purchases
Converted to pydantic_ai
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from pydantic_ai import RunContext

from backend.chatbot.agents.upselling_agent import run_upselling_agent
from backend.chatbot.agents.central_agent import run_central_agent
from backend.chatbot.agents.central_agent_utils import create_structured_input
from backend.chatbot.utils.agent_utils import get_or_create_user_state, save_user_state
from backend.db.cache_utils import get_user_state
from backend.db.db_utils import get_products
from backend.modules.products import get_product_images, get_products_by_business
from backend.struct import Customer, Vendor

from .base_agent import BaseAgent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

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
    system_prompt="""You are a vendor assistant. Your ONLY source of product information is the get_product_info tool.

RULES:
- ALWAYS call get_product_info before answering any product question. Never invent or assume products.
- Call get_product_info with no arguments to list all available products.
- Only mention products that are returned by the tool. If the tool returns nothing, say the vendor has no matching products.
- When a customer wants to purchase, fetch the payment link or provide bank transfer details.
- If information is missing (no products listed, no payment details set up), call notify_vendor to send a message directly to the vendor — NEVER ask the customer to contact the owner manually.
- Keep responses concise and conversational.""",
    deps_type=ProductAgentDeps,
)

product_agent = product_agent_base.agent


@product_agent.tool
async def get_product_info(
    ctx: RunContext[ProductAgentDeps], product_name: Optional[str] = None, category: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get products for this vendor from the database. Call with no product_name to list all products."""
    try:
        products = await get_products(
            business_id=ctx.deps.business_id,
            name=product_name if product_name else None,
            category=category,
        )
        for product in products:
            if product.get("id"):
                images = await get_product_images(product["id"])
                product["image_urls"] = images
        return products
    except Exception as e:
        return [{"error": f"Could not fetch products: {e}"}]


@product_agent.tool
async def fetch_payment_link(
    ctx: RunContext[ProductAgentDeps],
    product_id: Optional[str] = None,
    amount: Optional[float] = None,
) -> Optional[str]:
    """Fetch payment link for product purchase. Returns None if not available (use bank transfer instead)."""
    # TODO: Integrate with Paystack or other payment gateway
    return None


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


@product_agent.tool
async def notify_vendor(
    ctx: RunContext[ProductAgentDeps],
    message: str,
) -> Dict[str, Any]:
    """Send a message to the vendor via the central agent. Use this instead of drafting messages for the customer to send manually."""
    try:
        agent_input = await create_structured_input(
            sender="Agent",
            recipient="Vendor",
            message=message,
            customer=Customer(id=ctx.deps.user_id),
            business=Vendor(id=ctx.deps.business_id),
        )
        await run_central_agent(event_message=agent_input)
        return {"status": "vendor_notified", "message": "Message sent to vendor. The customer will be updated when the vendor responds."}
    except Exception as e:
        return {"status": "error", "message": f"Could not reach vendor: {e}"}


@product_agent.tool
async def upsell_products(
    ctx: RunContext[ProductAgentDeps],
    product_name: str,
    category: Optional[str] = None,
    intent: str = "enquiry",
    **kwargs,
) -> List[Dict[str, Any]]:
    """Upsell products"""
    return await run_upselling_agent(
        product_name,
        intent=intent,
        conversation_messages=ctx.deps.chat_history,
        business_id=ctx.deps.business_id,
        category=category,
        **kwargs,
    )


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

    # Get business info for dynamic system prompt
    business_info = user_state.get("business_information", {})
    if not business_info:
        from backend.db.db_utils import get_business_info

        business_info = await get_business_info(business_id) or {}
        user_state["business_information"] = business_info

    # Get chat history
    chat_history = user_state.get("chat_history", [])

    # Build dynamic system prompt with business account details
    dynamic_prompt = ""
    if business_info:
        bank_details = []
        if business_info.get("bank_name"):
            bank_details.append(f"Bank Name: {business_info.get('bank_name')}")
        if business_info.get("bank_account_name"):
            bank_details.append(f"Account Name: {business_info.get('bank_account_name')}")
        if business_info.get("bank_account_number"):
            bank_details.append(f"Account Number: {business_info.get('bank_account_number')}")

        if bank_details:
            dynamic_prompt = "\n\n**Business Payment Details:**\n" + "\n".join(bank_details)
            dynamic_prompt += "\n\nIf payment link is not available, provide these bank details for bank transfer."

    # Prepare prompt
    prompt_parts = [f"Customer message: {customer_message}"]

    # Always fetch products for this vendor — use product_name filter when specific, else fetch all
    cache_key = product_name if product_name.strip() != "NONE" else "__all__"
    products_cache = user_state.get("products", {})
    product_cache = products_cache.get(cache_key, {})

    if not product_cache.get("db_queried", False):
        name_filter = product_name if product_name.strip() != "NONE" else None
        try:
            products = await get_products(name=name_filter, category=product_category or None, business_id=business_id)
        except Exception:
            products = []
        product_cache = {"retrieved_results": products, "db_queried": True}
        user_state.setdefault("products", {})[cache_key] = product_cache

    products = product_cache.get("retrieved_results", [])

    if products:
        products_info = "\n".join(
            [
                f"- {p.get('name', p.get('product_name', ''))}: ${p.get('price', 0)} (Stock: {p.get('stock_quantity', p.get('items_left_in_stock', 0))})"
                for p in products[:10]
            ]
        )
        prompt_parts.append(f"\nVendor's products from database:\n{products_info}")
    else:
        prompt_parts.append("\nNo products found in this vendor's inventory.")

    if intent == "purchase":
        prompt_parts.append("\nCustomer intent: Purchase - try to fetch payment link first. If None, provide bank transfer details.")

    # Create dependencies
    deps = ProductAgentDeps(
        user_id=user_id or "",
        business_id=business_id or "",
        chat_history=chat_history,
    )

    # Run agent with dynamic prompt
    full_prompt = "\n".join(prompt_parts) + dynamic_prompt

    result = await product_agent.run(full_prompt, deps=deps)

    response = result.output

    # Update user state with serializable chat history
    user_state["chat_history"].extend([
    ModelRequest(parts=[UserPromptPart(content=customer_message)]),
    ModelResponse(parts=[TextPart(content=response)])])

    await save_user_state(user_id, business_id, user_state)

    return response, user_state
