"""
Logistics API endpoints
Handles logistics company interactions
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from backend.chatbot.interface.business_chat_interface import business_chat
from backend.db.cache_utils import get_inbox
from backend.db.db_utils import get_order_by_id
from backend.struct import BusinessRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/logistics", tags=["logistics"])


class LogisticsMessageRequest(BaseModel):
    """Logistics message. Reply context extracted from Redis chat_history."""
    business_id: str
    session_id: str
    sender: str = "logistics"
    message: str
    api_key: Optional[str] = None
    msg_date_time: Optional[str] = None


@router.post("/chat")
async def logistics_chat(
    request: LogisticsMessageRequest,
    background_tasks: BackgroundTasks
):
    """Handle logistics chat."""
    bid = (request.business_id or "").strip()
    if not bid:
        raise HTTPException(status_code=422, detail="business_id is required.")

    business_request = BusinessRequest(
        business_id=bid,
        session_id=request.session_id,
        sender=request.sender,
        message=request.message,
        msg_date_time=request.msg_date_time or datetime.now(),
    )

    try:
        response = await business_chat(business_request, background_tasks, debug=False)
    except Exception:
        logger.exception("logistics_chat failed")
        raise HTTPException(status_code=500, detail="Logistics chat processing failed.")

    return {"message": response or "Message processed", "business_id": bid}


@router.get("/inbox/{logistic_id}")
async def get_logistics_inbox(logistic_id: str):
    """Poll for messages sent to this logistics company by the central agent."""
    try:
        messages = await get_inbox(logistic_id)
    except Exception:
        logger.exception("logistics inbox fetch failed")
        raise HTTPException(status_code=500, detail="Failed to retrieve logistics inbox.")
    return {"logistic_id": logistic_id, "messages": messages}


@router.get("/orders/{order_id}/tracking")
async def get_order_tracking(order_id: str):
    """Get tracking information for an order from the database."""
    try:
        order = await get_order_by_id(order_id)
    except Exception:
        logger.exception("order tracking fetch failed")
        raise HTTPException(status_code=500, detail="Failed to retrieve order.")
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    return {
        "order_id": str(order["id"]),
        "order_number": order.get("order_number"),
        "status": order.get("status", "pending"),
        "tracking_number": order.get("tracking_number"),
        "logistic_id": str(order["logistic_id"]) if order.get("logistic_id") else None,
        "delivery_address": order.get("delivery_address"),
        "delivery_city": order.get("delivery_city"),
        "delivery_state": order.get("delivery_state"),
        "metadata": order.get("metadata"),
        "updated_at": order.get("updated_at"),
    }

