"""
Upselling: alternate / complementary options when the enquired product is unavailable.
Post-purchase marketing lives in ads_marketing_agent.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from pydantic_ai import RunContext

from backend.chatbot.agents.base_agent import BaseAgent
from backend.chatbot.utils.agent_utils import (
    check_tier_access,
    format_handoff_process_context,
    get_process_snapshot,
)
from backend.db.db_utils import get_business_info, get_products
from backend.modules.products import get_product_images
from backend.modules.products import search_products


class UpsellingAgentDeps(BaseModel):
    business_id: str
    api_key: Optional[str] = None
    upsell_tier_eligible: bool = None


async def _business_upsell_allowed(business_id: str, user_state: Optional[Dict[str, Any]]) -> bool:
    tier = None
    if user_state:
        tier = (user_state.get("business_information") or {}).get("tier")
    if tier is None and business_id:
        info = await get_business_info(business_id) or {}
        tier = info.get("tier")
    t = (str(tier) if tier is not None else "free").lower()
    return await check_tier_access(t, "upselling")


async def search_related_products(
    business_id: str,
    product_name: str,
    category: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    products = await search_products(
        product_name, business_id=business_id, category=category, limit=limit
    )
    for product in products:
        if product.get("id"):
            images = await get_product_images(product["id"])
            product["image_urls"] = images
    return products


async def search_cross_sell_products(
    business_id: str,
    upsell_tier_eligible: bool,
    product_category: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    if not upsell_tier_eligible:
        return [
            {
                "error": "plan_restricted",
                "message": "Cross-store recommendations are not enabled for this seller's subscription tier.",
            }
        ]
    products = await get_products(
        category=product_category,
        exclude_business_id=business_id or None,
        limit=limit,
    )
    for p in products:
        if p.get("id"):
            images = await get_product_images(p["id"])
            p["image_urls"] = images
    return products


async def search_complementary_same_store(
    business_id: str,
    product_category: str,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    return await get_products(
        business_id=business_id or None,
        category=product_category,
        limit=limit,
    )


upselling_agent_base = BaseAgent(
    system_prompt="""You are the **substitution specialist** — called only when the customer's desired product is unavailable (out of stock, not carried, or cannot be fulfilled).

**Workflow**
1. Call `get_related_products` with the unavailable product name to find same-store alternatives.
2. Call `get_complementary_products` for items that complement what the customer wanted.
3. If cross-store is allowed (tool will enforce tier), call `get_cross_sell_products` for one external option.

**Rules**
- Acknowledge the gap briefly. Offer up to 2 strong substitutes with clear reasons.
- Same-store first, cross-store only if tier allows. Never suggest other vendors otherwise.
- No hard sell.""",
    deps_type=UpsellingAgentDeps,
)

upselling_agent = upselling_agent_base.agent


@upselling_agent.tool
async def get_related_products(
    ctx: RunContext[UpsellingAgentDeps],
    product_name: str,
    category: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    return await search_related_products(
        ctx.deps.business_id, product_name, category, limit
    )


@upselling_agent.tool
async def get_cross_sell_products(
    ctx: RunContext[UpsellingAgentDeps],
    product_category: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    return await search_cross_sell_products(
        ctx.deps.business_id,
        ctx.deps.upsell_tier_eligible,
        product_category,
        limit,
    )


@upselling_agent.tool
async def get_complementary_products(
    ctx: RunContext[UpsellingAgentDeps],
    product_category: str,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    return await search_complementary_same_store(
        ctx.deps.business_id, product_category, limit
    )


async def run_upselling_agent(
    product: str,
    conversation_messages: Optional[List] = None,
    business_id: str = None,
    api_key: Optional[str] = None,
    situation_summary: str = "",
    user_state: Optional[Dict[str, Any]] = None,
    instructions: Optional[str] = None,
    process_id: Optional[str] = None,
    **kwargs,
) -> str:
    eligible = await _business_upsell_allowed(business_id or "", user_state)
    deps = UpsellingAgentDeps(
        business_id=business_id or "",
        api_key=api_key,
        upsell_tier_eligible=eligible,
    )
    extra = f"\nSituation: {situation_summary}" if situation_summary else ""
    scope = (
        "Cross-store allowed where tools permit."
        if eligible
        else "Same-store only; no other vendors."
    )
    proc_line = ""
    if user_state and (process_id or "").strip():
        proc = get_process_snapshot(user_state, process_id)
        if proc:
            proc_line = "\n" + format_handoff_process_context(str(process_id).strip(), proc)
    prompt = f"""Unavailable or unfulfillable focus product: {product}
Instruction: Suggest substitutes and close complements. {scope}{extra}{proc_line}

Conversation snippet:
{format_conversation(conversation_messages) if conversation_messages else ""}

Reply concisely."""
    run_kw: Dict[str, Any] = {}
    if instructions and instructions.strip():
        run_kw["instructions"] = instructions.strip()
    result = await upselling_agent.run(prompt, deps=deps, **run_kw)
    return result.output


def format_conversation(messages: List) -> str:
    if not messages:
        return ""

    formatted = []
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role", "user")
            content = msg.get("content", "")
        else:
            role = "user" if getattr(msg, "kind", None) == "request" else "assistant"
            parts = getattr(msg, "parts", [])
            content = (
                " ".join(getattr(p, "content", str(p)) for p in parts).strip()
                if parts
                else ""
            )
        formatted.append(f"{role}: {content}")

    return "\n".join(formatted)
