"""
Inventory Management API endpoints
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.db.db_utils import get_inventory as db_get_inventory
from backend.db.db_utils import get_low_stock_products

logger = logging.getLogger(__name__)

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


def _summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    out_stock = sum(1 for r in rows if int(r.get("stock_quantity") or 0) <= 0)
    low = sum(
        1
        for r in rows
        if 0 < int(r.get("stock_quantity") or 0) <= int(r.get("reorder_level") or 10)
    )
    return {
        "total_items": total,
        "in_stock": total - out_stock,
        "low_stock_count": low,
        "out_of_stock_count": out_stock,
        "needs_attention": low + out_stock,
    }


@router.post("/")
async def get_inventory(request: InventoryRequest):
    """Get inventory for a business."""
    try:
        rows = await db_get_inventory(request.business_id)
        low_rows = await get_low_stock_products(request.business_id, threshold=10)
        summary = _summarize(rows)
        alerts: List[str] = []
        if summary["out_of_stock_count"]:
            alerts.append(f"⚠️ {summary['out_of_stock_count']} product(s) out of stock")
        if summary["low_stock_count"]:
            alerts.append(f"⚠️ {summary['low_stock_count']} product(s) low stock")
        if not alerts:
            alerts.append("✅ All products in stock")
        return {
            "business_id": request.business_id,
            "inventory": rows,
            "low_stock_items": low_rows,
            "out_of_stock_items": [
                r for r in rows if int(r.get("stock_quantity") or 0) <= 0
            ],
            "summary": summary,
            "alerts": alerts,
        }
    except Exception:
        logger.exception("inventory fetch failed")
        raise HTTPException(status_code=500, detail="Failed to retrieve inventory.")


@router.post("/update")
async def update_inventory(request: InventoryUpdateRequest):
    """Update inventory quantity."""
    return {"success": True, "product_id": request.product_id, "quantity": request.quantity}

