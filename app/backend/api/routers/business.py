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
    """Business/logistics message. Reply context extracted by agent from chat history + recent_inbox."""
    vendor_id: Optional[str] = ""
    logistic_id: Optional[str] = ""
    session_id: str
    sender: str
    message: str
    recent_inbox: Optional[list] = None  # Inbox messages displayed (for agent context)
    api_key: Optional[str] = None
    msg_date_time: Optional[str] = None


@router.post("/chat")
async def business_chat_endpoint(
    request: BusinessMessageRequest,
    background_tasks: BackgroundTasks
):
    """Handle business/logistics chat. Agent extracts reply context from chat history."""
    business_request = BusinessRequest(
        vendor_id=request.vendor_id or "",
        logistic_id=request.logistic_id or "",
        session_id=request.session_id,
        sender=request.sender,
        message=request.message,
        recent_inbox=request.recent_inbox,
        msg_date_time=request.msg_date_time or datetime.now()
    )
    
    response = await business_chat(business_request, background_tasks, debug=False)
    
    return {
        "message": response or "Message processed",
        "vendor_id": request.vendor_id or request.logistic_id or "",
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

