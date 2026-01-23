"""
Utility functions for agents
"""
from typing import List, Dict, Any, Optional
from backend.db.cache_utils import get_user_state, modify_user_state
from backend.db.db_utils import get_business_info, get_products
from backend.config import config, TIER_FREE, TIER_GOLD, TIER_PLATINUM


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
    
    if not user_state:
        business_information = await get_business_info(business_id)
        user_state = {
            "chat_history": [],
            "business_information": business_information,
            "products": {},
            "processes": {}
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

