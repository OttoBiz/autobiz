"""
Products Module
Handles product-related operations
"""
from typing import List, Dict, Any, Optional
from backend.db.database import get_db
from backend.db.models import Product, Business
from backend.db.db_utils import get_products as db_get_products
from sqlalchemy import or_


async def get_product_by_id(product_id: str) -> Optional[Dict[str, Any]]:
    """Get product by ID"""
    with get_db() as db:
        product = db.query(Product).filter(Product.id == product_id).first()
        if product:
            return product.to_dict()
    return None


async def get_products_by_business(
    business_id: str,
    category: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get products by business ID"""
    with get_db() as db:
        query = db.query(Product).filter(Product.business_id == business_id)
        if category:
            query = query.filter(Product.product_category == category)
        products = query.limit(limit).all()
        return [p.to_dict() for p in products]


async def search_products(
    query: str,
    business_id: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Search products by query string"""
    return await db_get_products(name=query, category=category)


async def get_product_images(product_id: str) -> List[str]:
    """Get product image URLs for multimodal retrieval"""
    product = await get_product_by_id(product_id)
    if product:
        return product.get("image_urls", [])
    return []


async def update_product_stock(product_id: str, quantity: int):
    """Update product stock"""
    with get_db() as db:
        product = db.query(Product).filter(Product.id == product_id).first()
        if product:
            product.items_in_stock = quantity
            db.commit()
            return True
    return False

