"""
Post-purchase marketing: complementary (and tier-based cross-store) suggestions
after the bought item's logistics are in order. Separate from upselling (unavailable SKU paths).
"""
from typing import Any, Dict, List, Optional

from pydantic_ai import RunContext

from backend.chatbot.agents.base_agent import BaseAgent
from backend.chatbot.agents.upselling_agent import (
    UpsellingAgentDeps,
    _business_upsell_allowed,
    format_conversation,
    search_complementary_same_store,
    search_cross_sell_products,
    search_related_products,
)

ads_marketing_agent_base = BaseAgent(
    system_prompt="""You are the **post-purchase growth** assistant — called only after the customer has bought a product AND logistics/delivery is sorted.

**Workflow**
1. Call `get_complementary_products` with the purchased product's category for same-store complements.
2. Call `get_related_products` with the purchased product name for additional options.
3. If cross-store is allowed (tool enforces tier), call `get_cross_sell_products` for one external suggestion.

**Rules**
- Max 2 suggestions unless the customer asks for more. Short, helpful, not pushy.
- Never suggest substitutes for the purchased item — that's upselling's job.
- Prefer tools over guessing.""",
    deps_type=UpsellingAgentDeps,
)

ads_marketing_agent = ads_marketing_agent_base.agent


@ads_marketing_agent.tool
async def get_related_products(
    ctx: RunContext[UpsellingAgentDeps],
    product_name: str,
    category: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Related items from this business (same catalog search)."""
    return await search_related_products(
        ctx.deps.business_id, product_name, category, limit
    )


@ads_marketing_agent.tool
async def get_cross_sell_products(
    ctx: RunContext[UpsellingAgentDeps],
    product_category: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Other businesses' products; only if tier allows cross-store."""
    return await search_cross_sell_products(
        ctx.deps.business_id,
        ctx.deps.upsell_tier_eligible,
        product_category,
        limit,
    )


@ads_marketing_agent.tool
async def get_complementary_products(
    ctx: RunContext[UpsellingAgentDeps],
    product_category: str,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Complementary products from this business."""
    return await search_complementary_same_store(
        ctx.deps.business_id, product_category, limit
    )


async def run_ads_marketing_agent(
    customer_message: str,
    purchased_product: str,
    business_id: str = "",
    user_state: Optional[Dict[str, Any]] = None,
    logistics_summary: str = "",
    **kwargs,
) -> str:
    eligible = await _business_upsell_allowed(business_id or "", user_state)
    deps = UpsellingAgentDeps(
        business_id=business_id or "",
        api_key=kwargs.get("api_key"),
        upsell_tier_eligible=eligible,
    )
    chat_history = (user_state or {}).get("chat_history", []) if user_state else []
    log_line = f"\nLogistics/order status (trusted): {logistics_summary}" if logistics_summary else ""
    prompt = f"""Purchased product: {purchased_product}
Customer message: {customer_message}{log_line}

{format_conversation(chat_history[-6:]) if chat_history else ""}

Suggest complementary follow-ons appropriate after fulfillment is sorted."""
    result = await ads_marketing_agent.run(prompt, deps=deps)
    return result.output
