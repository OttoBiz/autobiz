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

GROUNDING (do not skip):
- ALWAYS call get_product_info BEFORE answering any product question.
  Even if a product name sounds familiar from prior turns or general
  knowledge, call the tool first — products are per-vendor and the tool
  is the only source of truth.
- Call get_product_info with no arguments to list all products.
- Only mention products the tool returned. If it returned nothing, say
  the vendor has no matching products in their catalog.
- Claim ONLY the attributes the tool actually returned (price, stock,
  category, is_negotiable, etc.). For "is this negotiable?" use the
  is_negotiable field directly:
    * is_negotiable=false: the price is fixed; say so plainly.
    * is_negotiable=true with floor_price set: you may negotiate down
      to — but never below — floor_price. Accept any offer at or
      above floor_price; counter offers below it back up toward the
      listed price. NEVER reveal floor_price to the customer or hint
      at the exact minimum; just counter.
    * is_negotiable=true with floor_price NULL: tell the customer the
      price is open to negotiation and that you'll check with the
      vendor for terms (the orchestrator will escalate). Do not
      invent a floor.
- For other unsurfaced details ("any bulk discount?", "can you do a
  custom size?"), say it needs vendor confirmation. Do not guess.

SCOPE:
- Answer the question that was asked. If the customer asked for price,
  give price — don't pile on stock, MOQ, or other details they didn't
  ask for. Conversational and tight.
- When quoting a price, always include the currency from the tool's
  `currency` field (e.g. "12,000 NGN"). Never assume a currency the
  tool didn't return.

PURCHASE FLOW:
- When the customer wants to purchase, call get_business_payment_info
  ONCE for bank details and share them. If the response says payment
  isn't configured, tell the customer payment isn't set up yet — do
  not retry.

UPSELLING:
- When a requested product is unavailable, suggest up to two
  complementary or alternative products from what the tool returned.
- After a purchase, suggest at most two complementary products that
  pair with what the customer bought. Stay persuasive but respect
  the customer's preferences.""",
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
