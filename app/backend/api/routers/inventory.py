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
    Get inventory for a business with stock levels and low stock alerts.
    Requires Platinum tier (or DEBUG mode).
    """
    with get_db() as db:
        business = db.query(Business).filter(Business.id == request.business_id).first()
        if not business:
            return {"error": "Business not found"}
        
        # Check tier access
        if not await check_tier_access(business.tier.value if business.tier else "free", "inventory"):
            return {"error": "Inventory management requires Platinum tier"}
        
        # Get inventory items
        inventory_items = db.query(InventoryItem).filter(
            InventoryItem.business_id == request.business_id
        ).all()
        
        # Also check products directly for comprehensive inventory
        products = db.query(Product).filter(
            Product.business_id == request.business_id,
            Product.is_active == True
        ).all()
        
        items = []
        low_stock_items = []
        out_of_stock_items = []
        
        # Process inventory items
        for item in inventory_items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                status = "out_of_stock" if item.quantity <= 0 else ("low_stock" if item.quantity <= item.reorder_level else "in_stock")
                item_data = {
                    "product_id": str(item.product_id),
                    "product_name": product.product_name if product else "Unknown",
                    "sku": product.sku if hasattr(product, 'sku') else None,
                    "quantity": item.quantity,
                    "reorder_level": item.reorder_level,
                    "status": status,
                    "needs_restock": item.quantity <= item.reorder_level
                }
                items.append(item_data)
                
                if status == "low_stock":
                    low_stock_items.append(item_data)
                elif status == "out_of_stock":
                    out_of_stock_items.append(item_data)
        
        # Process products without inventory items
        product_ids_with_items = {str(item.product_id) for item in inventory_items}
        for product in products:
            if str(product.id) not in product_ids_with_items:
                # Use product stock_quantity if available
                stock_qty = product.stock_quantity if hasattr(product, 'stock_quantity') else 0
                reorder_level = 10  # Default reorder level
                status = "out_of_stock" if stock_qty <= 0 else ("low_stock" if stock_qty <= reorder_level else "in_stock")
                
                item_data = {
                    "product_id": str(product.id),
                    "product_name": product.product_name if hasattr(product, 'product_name') else product.name,
                    "sku": product.sku if hasattr(product, 'sku') else None,
                    "quantity": stock_qty,
                    "reorder_level": reorder_level,
                    "status": status,
                    "needs_restock": stock_qty <= reorder_level
                }
                items.append(item_data)
                
                if status == "low_stock":
                    low_stock_items.append(item_data)
                elif status == "out_of_stock":
                    out_of_stock_items.append(item_data)
    
    return {
        "business_id": request.business_id,
        "inventory": items,
        "low_stock_items": low_stock_items,
        "out_of_stock_items": out_of_stock_items,
        "summary": {
            "total_items": len(items),
            "in_stock": len([i for i in items if i["status"] == "in_stock"]),
            "low_stock_count": len(low_stock_items),
            "out_of_stock_count": len(out_of_stock_items),
            "needs_attention": len(low_stock_items) + len(out_of_stock_items)
        },
        "alerts": [
            f"⚠️ {len(low_stock_items)} product(s) running low on stock",
            f"🚨 {len(out_of_stock_items)} product(s) out of stock"
        ] if (low_stock_items or out_of_stock_items) else ["✅ All products in stock"]
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

