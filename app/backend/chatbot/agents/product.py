"""Product agent — handles product inquiries, purchases, and upsell suggestions."""

from typing import Any, Dict, List, Optional

from pydantic_ai import Agent, RunContext

from backend.chatbot.agents.deps import AgentDeps
from backend.config import MODEL_NAME
from backend.db.db_utils import get_business_info, get_products

product_agent = Agent(
    model=MODEL_NAME,
    deps_type=AgentDeps,
    system_prompt="""You are a vendor assistant. Your ONLY source of product information is the get_product_info tool.

RULES:
- ALWAYS call get_product_info before answering any product question. Never invent or assume products.
- Call get_product_info with no arguments to list all available products.
- Only mention products that are returned by the tool. If the tool returns nothing, say the vendor has no matching products.
- When a customer wants to purchase, call get_business_payment_info ONCE to get bank details and offer them to the customer. If the response says payment is not configured, tell the customer payment isn't set up yet — do not retry.
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
        return await get_products(
            business_id=str(ctx.deps.business_id),
            name=product_name if product_name else "",
            category=category if category else "",
        )
    except Exception as e:
        return [{"error": f"Could not fetch products: {e}"}]


@product_agent.tool
async def get_business_payment_info(
    ctx: RunContext[AgentDeps],
) -> Dict[str, Any]:
    """Get the vendor's bank/payment details so the customer can pay.

    Returns a dict with `configured: True` and bank fields when set up, or
    `configured: False` with a `message` when the vendor hasn't entered
    payment details yet — call ONCE per turn; the response is final.
    """
    business = await get_business_info(str(ctx.deps.business_id))
    if not business:
        return {
            "configured": False,
            "message": "Business record not found.",
        }

    bank_name = business.get("bank_name") or ""
    account_number = business.get("bank_account_number") or ""
    account_name = business.get("bank_account_name") or ""

    if not (bank_name and account_number):
        return {
            "configured": False,
            "message": "The vendor hasn't set up bank payment details yet.",
        }

    return {
        "configured": True,
        "bank_name": bank_name,
        "bank_account_number": account_number,
        "bank_account_name": account_name,
    }
