"""
Business API endpoints
Handles business owner interactions
"""
import logging
import random
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from backend.chatbot.interface.business_chat_interface import business_chat
from backend.db.cache_utils import get_inbox
from backend.db.db_utils import get_business_info, get_logistics_companies
from backend.struct import BusinessRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/business", tags=["business"])


class BusinessMessageRequest(BaseModel):
    """Business message. Reply context extracted from Redis chat_history."""
    business_id: str
    session_id: str
    sender: str
    message: str
    api_key: Optional[str] = None
    msg_date_time: Optional[str] = None


@router.post("/chat")
async def business_chat_endpoint(
    business_request: BusinessMessageRequest,
    background_tasks: BackgroundTasks
):
    """Handle business/logistics chat."""
    bid = (business_request.business_id or "").strip()
    if not bid:
        raise HTTPException(status_code=422, detail="business_id is required.")

    req = BusinessRequest(
        business_id=bid,
        session_id=business_request.session_id,
        sender=business_request.sender,
        message=business_request.message,
        msg_date_time=business_request.msg_date_time or datetime.now(),
    )

    try:
        response = await business_chat(req, background_tasks, debug=False)
    except Exception:
        logger.exception("business_chat failed")
        raise HTTPException(status_code=500, detail="Business chat processing failed.")

    return {"message": response or "Message processed", "business_id": req.business_id}


@router.get("/delivery-partner/{business_id}")
async def get_delivery_partner(business_id: str):
    """Partner logistics from DB, or a random registered carrier when none (simulation UI)."""
    bid = (business_id or "").strip()
    if not bid:
        raise HTTPException(status_code=422, detail="business_id required")
    info = await get_business_info(bid)
    if not info:
        raise HTTPException(status_code=404, detail="Business not found")
    pid = info.get("partner_logistic_id")
    if pid:
        p = await get_business_info(str(pid))
        return {
            "partner_logistic_id": str(pid),
            "partner_name": (p or {}).get("name"),
            "source": "db_partner",
        }
    lst = await get_logistics_companies(limit=20)
    if not lst:
        return {"partner_logistic_id": None, "partner_name": None, "source": "none"}
    pick = random.choice(lst)
    return {
        "partner_logistic_id": str(pick["id"]),
        "partner_name": pick.get("name"),
        "source": "random_registry",
    }


@router.get("/inbox/{vendor_id}")
async def get_vendor_inbox(vendor_id: str):
    """Poll for messages sent to this vendor by the central agent."""
    try:
        messages = await get_inbox(vendor_id)
    except Exception:
        logger.exception("vendor inbox fetch failed")
        raise HTTPException(status_code=500, detail="Failed to retrieve vendor inbox.")
    return {"vendor_id": vendor_id, "messages": messages}


@router.post("/businessChat")
async def business_chat_endpoint_legacy(
    request: BusinessMessageRequest,
    background_tasks: BackgroundTasks
):
    """Legacy endpoint - redirects to /chat"""
    return await business_chat_endpoint(request, background_tasks)

