"""
Customer API endpoints
Handles customer requests and interactions
"""
from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form, Request
from typing import Optional, List
from pydantic import BaseModel
from backend.chatbot.interface.user_chat_interface import chat
from backend.db.cache_utils import get_inbox
from backend.struct import UserRequest
from datetime import datetime

router = APIRouter(prefix="/customer", tags=["customer"])


class CustomerMessageRequest(BaseModel):
    """Customer message request"""
    user_id: str
    vendor_id: str
    session_id: str
    message: str
    api_key: Optional[str] = None
    msg_date_time: Optional[str] = None


@router.post("/chat")
async def customer_chat(
    http_request: Request,
    background_tasks: BackgroundTasks
):
    """
    Handle customer chat messages with file attachments.
    Supports both JSON (for frontend without files) and Form data (for file uploads).
    Supports images, PDFs, and audio files.
    
    Usage:
    - JSON: POST with Content-Type: application/json, body: CustomerMessageRequest
    - FormData: POST with Content-Type: multipart/form-data, include files if needed
    """
    content_type = http_request.headers.get("content-type", "")
    
    # Handle JSON request (from frontend without files)
    if "application/json" in content_type:
        body = await http_request.json()
        request = CustomerMessageRequest(**body)
        user_request = UserRequest(
            user_id=request.user_id,
            vendor_id=request.vendor_id,
            session_id=request.session_id,
            message=request.message,
            msg_date_time=request.msg_date_time or datetime.now()
        )
        files_list = None
    # Handle Form data request (with file uploads)
    else:
        form_data = await http_request.form()
        user_id = form_data.get("user_id")
        vendor_id = form_data.get("vendor_id")
        session_id = form_data.get("session_id")
        message = form_data.get("message", "")
        
        if not user_id or not vendor_id:
            return {"error": "Missing required fields: user_id, vendor_id"}
        
        user_request = UserRequest(
            user_id=str(user_id),
            vendor_id=str(vendor_id),
            session_id=str(session_id) if session_id else f"session-{datetime.now()}",
            message=str(message) if message else "",
            msg_date_time=datetime.now()
        )
        
        # Get files from form
        files_list = []
        file_items = form_data.getlist("files")
        for file_item in file_items:
            if isinstance(file_item, UploadFile):
                files_list.append(file_item)
        
        files_list = files_list if files_list else None
    
    # Pass files to chat function
    response = await chat(
        user_request, 
        background_tasks, 
        reset_user_state=False,
        files=files_list
    )
    
    return {
        "message": response,
        "user_id": user_request.user_id,
        "vendor_id": user_request.vendor_id,
        "files_received": len(files_list) if files_list else 0
    }


@router.get("/inbox/{user_id}")
async def get_customer_inbox(user_id: str):
    """Poll for messages sent to this customer by the central agent (e.g. order updates, delivery notifications)."""
    messages = await get_inbox(user_id)
    return {"user_id": user_id, "messages": messages}

