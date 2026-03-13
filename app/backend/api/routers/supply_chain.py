"""
Supply Chain API endpoints
"""
from fastapi import APIRouter
from typing import Optional
from pydantic import BaseModel
from backend.db.database import get_db
from backend.db.models import SupplyChain, Business

router = APIRouter(prefix="/supply-chain", tags=["supply_chain"])


class SupplyChainRequest(BaseModel):
    """Supply chain request"""
    business_id: str
    api_key: Optional[str] = None


@router.post("/")
async def get_supply_chain(request: SupplyChainRequest):
    """
    Get supply chain information for a business with delivery status tracking.
    """
    from datetime import datetime, timezone
    
    with get_db() as db:
        supply_chain_items = db.query(SupplyChain).filter(
            SupplyChain.business_id == request.business_id
        ).all()
        
        items = []
        pending_items = []
        delivered_items = []
        overdue_items = []
        
        current_date = datetime.now(timezone.utc)
        
        for item in supply_chain_items:
            # Determine delivery status
            delivery_status = "pending"
            if item.actual_delivery_date:
                delivery_status = "delivered"
            elif item.expected_delivery_date and item.expected_delivery_date < current_date:
                delivery_status = "overdue"
            
            # Calculate progress
            progress_percentage = 0
            if item.quantity_ordered > 0:
                progress_percentage = int((item.quantity_received / item.quantity_ordered) * 100)
            
            item_data = {
                "id": str(item.id),
                "supplier_name": item.supplier_name,
                "product_id": str(item.product_id) if item.product_id else None,
                "quantity_ordered": item.quantity_ordered,
                "quantity_received": item.quantity_received,
                "quantity_pending": item.quantity_ordered - item.quantity_received,
                "status": item.status,
                "delivery_status": delivery_status,
                "progress_percentage": progress_percentage,
                "expected_delivery_date": item.expected_delivery_date.isoformat() if item.expected_delivery_date else None,
                "actual_delivery_date": item.actual_delivery_date.isoformat() if item.actual_delivery_date else None,
                "is_overdue": delivery_status == "overdue",
                "is_delivered": delivery_status == "delivered"
            }
            
            items.append(item_data)
            
            # Categorize items
            if delivery_status == "pending":
                pending_items.append(item_data)
            elif delivery_status == "delivered":
                delivered_items.append(item_data)
            elif delivery_status == "overdue":
                overdue_items.append(item_data)
    
    return {
        "business_id": request.business_id,
        "supply_chain": items,
        "summary": {
            "total_orders": len(items),
            "pending": len(pending_items),
            "delivered": len(delivered_items),
            "overdue": len(overdue_items),
            "completion_rate": int((len(delivered_items) / len(items)) * 100) if items else 0
        },
        "pending_items": pending_items,
        "delivered_items": delivered_items,
        "overdue_items": overdue_items,
        "delivery_status": {
            "on_time": len([i for i in items if i["is_delivered"] and not i["is_overdue"]]),
            "overdue": len(overdue_items),
            "pending": len(pending_items)
        },
        "alerts": [
            f"⚠️ {len(overdue_items)} order(s) overdue",
            f"📦 {len(pending_items)} order(s) pending delivery"
        ] if (overdue_items or pending_items) else ["✅ All orders delivered"]
    }

