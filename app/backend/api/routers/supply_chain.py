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
    Get supply chain information for a business.
    """
    with get_db() as db:
        supply_chain_items = db.query(SupplyChain).filter(
            SupplyChain.business_id == request.business_id
        ).all()
        
        items = []
        for item in supply_chain_items:
            items.append({
                "id": str(item.id),
                "supplier_name": item.supplier_name,
                "product_id": str(item.product_id) if item.product_id else None,
                "quantity_ordered": item.quantity_ordered,
                "quantity_received": item.quantity_received,
                "status": item.status,
                "expected_delivery_date": item.expected_delivery_date.isoformat() if item.expected_delivery_date else None,
                "actual_delivery_date": item.actual_delivery_date.isoformat() if item.actual_delivery_date else None
            })
    
    return {
        "business_id": request.business_id,
        "supply_chain": items
    }

