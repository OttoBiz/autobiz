"""
Products Module
Handles product-related operations
"""

from typing import Any, Dict, List, Optional

from backend.db.db_utils import (
    get_product_by_id as db_get_product_by_id,
)
from backend.db.db_utils import (
    get_products,
)
from backend.db.db_utils import (
    search_products as db_search_products,
)
from backend.db.db_utils import (
    update_product_stock as db_update_product_stock,
)


async def get_product_by_id(product_id: str) -> Optional[Dict[str, Any]]:
    """Get product by ID"""
    return await db_get_product_by_id(product_id)


async def get_products_by_business(
    business_id: str, category: Optional[str] = None, limit: int = 50
) -> List[Dict[str, Any]]:
    """Get products by business ID"""
    return await get_products(business_id=business_id, category=category)


async def search_products(
    query: str,
    business_id: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Search products by query string"""
    return await db_search_products(query=query, business_id=business_id, limit=limit)


async def get_product_images(product_id: str) -> List[str]:
    """Get product image URLs for multimodal retrieval"""
    product = await get_product_by_id(product_id)
    if product:
        return product.get("image_urls", [])
    return []


async def update_product_stock(product_id: str, quantity: int) -> bool:
    """Update product stock"""
    result = await db_update_product_stock(product_id, quantity)
    return result is not None
