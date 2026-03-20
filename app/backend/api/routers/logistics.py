"""
Logistics API endpoints
Handles logistics company interactions
"""
from fastapi import APIRouter, BackgroundTasks
from typing import Optional
from pydantic import BaseModel
from backend.chatbot.interface.business_chat_interface import business_chat
from backend.db.cache_utils import get_inbox
from backend.db.db_utils import get_order_by_id
from backend.struct import BusinessRequest
from datetime import datetime

router = APIRouter(prefix="/logistics", tags=["logistics"])


class LogisticsMessageRequest(BaseModel):
    """Logistics message. Reply context extracted by agent from chat history + recent_inbox."""
    vendor_id: Optional[str] = ""
    logistic_id: str
    session_id: str
    sender: str = "logistics"
    message: str
    recent_inbox: Optional[list] = None
    api_key: Optional[str] = None
    msg_date_time: Optional[str] = None


@router.post("/chat")
async def logistics_chat(
    request: LogisticsMessageRequest,
    background_tasks: BackgroundTasks
):
    """Handle logistics chat. Agent extracts reply context from chat history."""
    business_request = BusinessRequest(
        vendor_id=request.vendor_id or "",
        logistic_id=request.logistic_id,
        session_id=request.session_id,
        sender=request.sender,
        message=request.message,
        recent_inbox=request.recent_inbox,
        msg_date_time=request.msg_date_time or datetime.now()
    )
    
    response = await business_chat(business_request, background_tasks, debug=False)
    
    return {
        "message": response or "Message processed",
        "logistic_id": request.logistic_id
    }


@router.get("/inbox/{logistic_id}")
async def get_logistics_inbox(logistic_id: str):
    """Poll for messages sent to this logistics company by the central agent."""
    messages = await get_inbox(logistic_id)
    return {"logistic_id": logistic_id, "messages": messages}


@router.get("/orders/{order_id}/tracking")
async def get_order_tracking(order_id: str):
    """Get tracking information for an order from the database."""
    order = await get_order_by_id(order_id)
    if not order:
        return {"error": "Order not found", "order_id": order_id}
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

