"""
Customer API endpoints
Handles customer requests and interactions
"""
from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form
from typing import Optional, List
from pydantic import BaseModel
from backend.chatbot.interface.user_chat_interface import chat
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
    user_id: str = Form(...),
    vendor_id: str = Form(...),
    session_id: str = Form(...),
    message: str = Form(""),
    api_key: Optional[str] = Form(None),
    files: Optional[List[UploadFile]] = File(None),
    background_tasks: BackgroundTasks = None
):
    """
    Handle customer chat messages with file attachments.
    Supports images, PDFs, and audio files.
    """
    user_request = UserRequest(
        user_id=user_id,
        vendor_id=vendor_id,
        session_id=session_id,
        message=message,
        msg_date_time=datetime.now()
    )
    
    # Pass files to chat function
    response = await chat(
        user_request, 
        background_tasks, 
        reset_user_state=False,
        files=files
    )
    
    return {
        "message": response,
        "user_id": user_id,
        "vendor_id": vendor_id,
        "files_received": len(files) if files else 0
    }

