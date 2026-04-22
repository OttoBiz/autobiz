"""Product agent — handles product inquiries, purchases, and upsell suggestions."""

from typing import Any, Dict, List, Optional

from pydantic_ai import Agent, RunContext

from backend.chatbot.agents.central import AgentDeps
from backend.config import MODEL_NAME
from backend.db.cache_utils import get_user_state
from backend.db.db_utils import get_products
from backend.modules.products import get_product_images

product_agent = Agent(
    model=MODEL_NAME,
    deps_type=AgentDeps,
    system_prompt="""You are a vendor assistant. Your ONLY source of product information is the get_product_info tool.

RULES:
- ALWAYS call get_product_info before answering any product question. Never invent or assume products.
- Call get_product_info with no arguments to list all available products.
- Only mention products that are returned by the tool. If the tool returns nothing, say the vendor has no matching products.
- When a customer wants to purchase, fetch the payment link or provide bank transfer details.
- If information is missing (no products listed, no payment details set up), return a clear message stating what's unavailable so the orchestrator can handle it.
- Keep responses concise and conversational.

UPSELLING:
- When a requested product is unavailable, suggest up to two complementary or alternative products from the vendor's catalog.
- After a purchase, suggest at most two complementary products that pair with what the customer bought. Stay persuasive but respect customer preferences.""",
)


@product_agent.tool
async def get_product_info(
    ctx: RunContext[AgentDeps],
    product_name: Optional[str] = None,
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Get relevant products for this vendor's business (per customer's enquiry) from the database.
    Call with no product_name to list all products."""

    try:
        products = await get_products(
            business_id=ctx.deps.business_id,
            name=product_name if product_name else "",
            category=category if category else "",
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
    ctx: RunContext[AgentDeps],
    product_id: Optional[str] = None,
    amount: Optional[float] = None,
) -> Optional[str]:
    """Fetch payment link for product purchase. Returns None if not available (use bank transfer instead)."""
    # TODO: Integrate with Paystack or other payment gateway
    return None


@product_agent.tool
async def get_business_payment_info(
    ctx: RunContext[AgentDeps],
) -> Dict[str, str]:
    """Get business payment information (bank account details)"""
    user_state = await get_user_state(ctx.deps.user_id, ctx.deps.business_id)
    business_info = user_state.get("business_information", {})

    return {
        "bank_name": business_info.get("bank_name", ""),
        "bank_account_number": business_info.get("bank_account_number", ""),
        "bank_account_name": business_info.get("bank_account_name", ""),
        "paystack_public_key": business_info.get("paystack_public_key", ""),
    }
