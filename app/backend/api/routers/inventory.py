"""
Inventory Management API endpoints
"""
from fastapi import APIRouter
from typing import Optional, List
from pydantic import BaseModel
from backend.db.database import get_db
from backend.db.models import InventoryItem, Product, Business
from backend.chatbot.agents.agent_utils import check_tier_access
from backend.config import TIER_PLATINUM

router = APIRouter(prefix="/inventory", tags=["inventory"])


class InventoryRequest(BaseModel):
    """Inventory request"""
    business_id: str
    api_key: Optional[str] = None


class InventoryUpdateRequest(BaseModel):
    """Inventory update request"""
    business_id: str
    product_id: str
    quantity: int
    reorder_level: Optional[int] = None


@router.post("/")
async def get_inventory(request: InventoryRequest):
    """
    Get inventory for a business.
    Requires Platinum tier.
    """
    with get_db() as db:
        business = db.query(Business).filter(Business.id == request.business_id).first()
        if not business:
            return {"error": "Business not found"}
        
        # Check tier access
        if not await check_tier_access(business.tier.value if business.tier else "free", "inventory"):
            return {"error": "Inventory management requires Platinum tier"}
        
        inventory_items = db.query(InventoryItem).filter(
            InventoryItem.business_id == request.business_id
        ).all()
        
        items = []
        for item in inventory_items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            items.append({
                "product_id": str(item.product_id),
                "product_name": product.product_name if product else "Unknown",
                "quantity": item.quantity,
                "reorder_level": item.reorder_level,
                "status": "low_stock" if item.quantity <= item.reorder_level else "in_stock"
            })
    
    return {
        "business_id": request.business_id,
        "inventory": items,
        "low_stock_items": [item for item in items if item["status"] == "low_stock"]
    }


@router.post("/update")
async def update_inventory(request: InventoryUpdateRequest):
    """
    Update inventory quantity.
    """
    with get_db() as db:
        inventory_item = db.query(InventoryItem).filter(
            InventoryItem.business_id == request.business_id,
            InventoryItem.product_id == request.product_id
        ).first()
        
        if inventory_item:
            inventory_item.quantity = request.quantity
            if request.reorder_level:
                inventory_item.reorder_level = request.reorder_level
        else:
            inventory_item = InventoryItem(
                business_id=request.business_id,
                product_id=request.product_id,
                quantity=request.quantity,
                reorder_level=request.reorder_level or 10
            )
            db.add(inventory_item)
        
        db.commit()
    
    return {
        "success": True,
        "product_id": request.product_id,
        "quantity": request.quantity
    }

