"""
Business API endpoints
Handles business owner interactions
"""
from fastapi import APIRouter, BackgroundTasks
from typing import Optional
from pydantic import BaseModel
from backend.chatbot.interface.business_chat_interface import business_chat
from backend.db.cache_utils import get_inbox
from backend.struct import BusinessRequest
from datetime import datetime

router = APIRouter(prefix="/business", tags=["business"])


class BusinessMessageRequest(BaseModel):
    """Business message request"""
    user_id: str
    vendor_id: str
    logistic_id: Optional[str] = ""
    session_id: str
    sender: str
    message: str
    product_name: Optional[str] = ""
    product_price: Optional[str] = ""
    message_type: str
    api_key: Optional[str] = None
    msg_date_time: Optional[str] = None


@router.post("/chat")
async def business_chat_endpoint(
    request: BusinessMessageRequest,
    background_tasks: BackgroundTasks
):
    """
    Handle business owner chat messages.
    Allows businesses to interact with the system and respond to customer inquiries.
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
        "vendor_id": request.vendor_id
    }


@router.get("/inbox/{vendor_id}")
async def get_vendor_inbox(vendor_id: str):
    """Poll for messages sent to this vendor by the central agent."""
    messages = await get_inbox(vendor_id)
    return {"vendor_id": vendor_id, "messages": messages}


@router.post("/businessChat")
async def business_chat_endpoint_legacy(
    request: BusinessMessageRequest,
    background_tasks: BackgroundTasks
):
    """Legacy endpoint - redirects to /chat"""
    return await business_chat_endpoint(request, background_tasks)

