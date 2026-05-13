"""
Utility functions for agents
"""
from typing import Any, Dict, List, Optional, Tuple
from backend.db.cache_utils import get_user_state, modify_user_state
from backend.db.db_utils import get_business_info, get_products
from backend.config import config, TIER_FREE, TIER_GOLD, TIER_PLATINUM


def normalize_business_tier(raw: Optional[Any]) -> str:
    """Lowercase tier slug for ``check_tier_access``; empty/None → free."""
    if raw is None:
        return TIER_FREE
    s = str(raw).strip().lower()
    return s if s else TIER_FREE


async def resolve_seller_tier_for_upsell(
    business_id: str,
    user_state: Optional[Dict[str, Any]] = None,
    tier_hint: Optional[str] = None,
) -> Tuple[str, bool]:
    """
    Normalized seller tier and whether upselling/cross-sell (cross-store) features apply.

    ``tier_hint`` wins when non-empty (e.g. from orchestrator handoff). Otherwise uses
    ``user_state['business_information']['tier']``, then DB for ``business_id``.
    """
    if tier_hint is not None and str(tier_hint).strip():
        t = normalize_business_tier(tier_hint)
        return t, await check_tier_access(t, "upselling")
    tier = None
    if user_state:
        tier = (user_state.get("business_information") or {}).get("tier")
    if tier is None and (business_id or "").strip():
        info = await get_business_info((business_id or "").strip()) or {}
        tier = info.get("tier")
    t = normalize_business_tier(tier)
    return t, await check_tier_access(t, "upselling")


async def check_tier_access(business_tier: str, feature: str) -> bool:
    """
    Check if a business tier has access to a feature.
    
    Args:
        business_tier: Business tier (free, gold, platinum)
        feature: Feature to check access for
        
    Returns:
        True if access is allowed, False otherwise
    """
    if config.DEBUG:
        return True
    
    tier_access = {
        TIER_FREE: {
            "logistics": False,
            "upselling": False,
            "inventory": False,
            "user_analytics": False,
            "business_analytics": False,  # Only 3 months
        },
        TIER_GOLD: {
            "logistics": True,
            "upselling": True,
            "inventory": False,
            "user_analytics": False,
            "business_analytics": True,
        },
        TIER_PLATINUM: {
            "logistics": True,
            "upselling": True,
            "inventory": True,
            "user_analytics": True,
            "business_analytics": True,
        }
    }
    
    return tier_access.get(business_tier, {}).get(feature, False)


async def get_or_create_user_state(user_id: str, business_id: str) -> Dict[str, Any]:
    """
    Get user state from cache or create a new one.
    
    Args:
        user_id: User ID
        business_id: Business ID
        
    Returns:
        User state dictionary
    """
    user_state = await get_user_state(user_id, business_id)

    if user_state is None:
        # None = Redis error; return a minimal safe state without overwriting Redis
        business_information = await get_business_info(business_id)
        user_state = {
            "chat_history": [],
            "business_information": business_information,
            "products": {},
            "processes": {},
        }
    elif not user_state:
        # {} = genuinely new user; same initialisation but this state will be saved normally
        business_information = await get_business_info(business_id)
        user_state = {
            "chat_history": [],
            "business_information": business_information,
            "products": {},
            "processes": {},
        }

    return user_state


async def save_user_state(user_id: str, business_id: str, user_state: Dict[str, Any]):
    """
    Save user state to cache.
    
    Args:
        user_id: User ID
        business_id: Business ID
        user_state: User state dictionary
    """
    await modify_user_state(user_id, business_id, user_state)


def format_chat_history(chat_history: List[Dict]) -> str:
    
    """
    Format chat history for agent prompts.
    
    Args:
        chat_history: List of chat messages
        
    Returns:
        Formatted string
    """
    if not chat_history:
        return "No previous conversation."
    
    formatted = []
    for msg in chat_history[-10:]:  # Last 10 messages
        role = msg.get("role", "user")
        content = msg.get("content", "")
        name = msg.get("name", "")
        formatted.append(f"{name or role}: {content}")
    
    return "\n".join(formatted)


def get_process_snapshot(user_state: Dict[str, Any], process_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return processes[process_id] if it exists and is a dict."""
    if not process_id or not str(process_id).strip():
        return None
    procs = user_state.get("processes")
    if not isinstance(procs, dict):
        return None
    raw = procs.get(str(process_id).strip())
    return raw if isinstance(raw, dict) else None


def format_handoff_process_context(process_id: str, proc: Dict[str, Any]) -> str:
    """Single line for specialist prompts (not duplicated in instructions slim profiles)."""
    parts = [f"process_id={process_id}"]
    for k in ("product_name", "quantity", "order_id", "task_type", "status", "order_number"):
        v = proc.get(k)
        if v is not None and str(v).strip() != "":
            parts.append(f"{k}={v}")
    return "**Session process (handoff):** " + "; ".join(parts)

