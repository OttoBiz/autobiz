from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from backend.whatsapp.utils import whatsapp


router = APIRouter(tags=["whatsapp"])


@router.get("/webhook")
def verification(request: Request):
    response = whatsapp.verify_webhook(request)
    return PlainTextResponse(response)


@router.post("/webhook")
async def notification(request: Request):
    response = await whatsapp.handle_webhook(request)
    return PlainTextResponse(response)