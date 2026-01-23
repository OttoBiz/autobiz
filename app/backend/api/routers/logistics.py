"""
Logistics API endpoints
Handles logistics company interactions
"""
from fastapi import APIRouter, BackgroundTasks
from typing import Optional
from pydantic import BaseModel
from backend.chatbot.interface.business_chat_interface import business_chat
from backend.struct import BusinessRequest
from datetime import datetime

router = APIRouter(prefix="/logistics", tags=["logistics"])


class LogisticsMessageRequest(BaseModel):
    """Logistics message request"""
    user_id: str
    vendor_id: str
    logistic_id: str
    session_id: str
    sender: str
    message: str
    product_name: Optional[str] = ""
    product_price: Optional[str] = ""
    message_type: str = "Logistic planning"
    api_key: Optional[str] = None
    msg_date_time: Optional[str] = None


@router.post("/chat")
async def logistics_chat(
    request: LogisticsMessageRequest,
    background_tasks: BackgroundTasks
):
    """
    Handle logistics company chat messages.
    Allows logistics companies to coordinate deliveries with vendors and customers.
    """
    business_request = BusinessRequest(
        user_id=request.user_id,
        vendor_id=request.vendor_id,
        logistic_id=request.logistic_id,
        session_id=request.session_id,
        sender=request.sender,
        message=request.message,
        product_name=request.product_name,
        product_price=request.product_price,
        message_type=request.message_type,
        msg_date_time=request.msg_date_time or datetime.now()
    )
    
    response = await business_chat(business_request, background_tasks, debug=False)
    
    return {
        "message": response or "Message processed",
        "logistic_id": request.logistic_id
    }


@router.get("/orders/{order_id}/tracking")
async def get_order_tracking(order_id: str):
    """
    Get tracking information for an order.
    """
    # TODO: Implement order tracking
    return {
        "order_id": order_id,
        "status": "pending",
        "tracking_number": None,
        "estimated_delivery": None
    }

