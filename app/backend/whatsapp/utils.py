"""
WhatsApp Integration - Refactored for Pydantic AI agents
Plug and play modularity for WhatsApp interface
"""
import hashlib
import hmac
import json
import os
from typing import Union, Optional
from urllib.parse import parse_qs
from pydantic import BaseModel
import requests
from dotenv import load_dotenv
import logging
from backend.config import config

load_dotenv()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
APP_SECRET = os.getenv("APP_SECRET", "")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "") or config.WHATSAPP_API_KEY
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "") or config.WHATSAPP_PHONE_NUMBER_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MessageRequest(BaseModel):
    """WhatsApp message request"""
    message: str
    sender_id: str
    recipient_id: str


class UserRequest(BaseModel):
    """User request from WhatsApp"""
    user_id: str
    vendor_id: str
    message: str
    session_id: Optional[str] = None


class BusinessRequest(BaseModel):
    """Business request from WhatsApp"""
    sender: str
    message: str
    product_name: str
    product_price: str
    user_id: str
    vendor_id: str
    logistic_id: str
    message_type: str


class WhatsappBot:
    """WhatsApp bot handler - modular and pluggable"""
    
    def __init__(self, page_access_token: Optional[str] = None, 
                 app_secret: Optional[str] = None, 
                 verify_token: Optional[str] = None):
        self.page_access_token = page_access_token or PAGE_ACCESS_TOKEN
        self.app_secret = app_secret or APP_SECRET
        self.verify_token = verify_token or VERIFY_TOKEN

    def verify_webhook(self, request) -> str:
        """Verify WhatsApp webhook"""
        query_params = parse_qs(str(request.query_params))
        mode = query_params.get("hub.mode", None)
        token = query_params.get("hub.verify_token", None)
        challenge = query_params.get("hub.challenge", None)

        if mode and token:
            if mode[0] == "subscribe" and token[0] == self.verify_token:
                return challenge[0]
            else:
                return "Invalid verification token"
        return "Invalid request"

    async def handle_webhook(self, request, background_task) -> str:
        """Handle incoming WhatsApp webhook"""
        if request.method == "POST":
            body = await request.body()
            signature = request.headers.get("X-Hub-Signature", "")

            if not self.verify_signature(body, signature):
                logger.error("Invalid signature")
                return "Invalid signature", 403

            try:
                data = json.loads(body)
                entry = data.get("entry", [{}])[0]
                messaging_events = [
                    changes.get("value")
                    for changes in entry.get("changes", [])
                    if changes.get("value")
                ]

                if not messaging_events or messaging_events[0].get("statuses"):
                    return "OK"

                recipient_id = messaging_events[0]["metadata"]["display_phone_number"]
                phone_number_id = messaging_events[0]["metadata"]["phone_number_id"]
                message = messaging_events[0]["messages"][0]
                sender_id = message["from"]
                
                await self.handle_message(sender_id, phone_number_id, message, background_task)
            except Exception as e:
                logger.error(f"Error handling webhook: {e}")
                return "Error processing webhook"
        
        return "OK"

    async def handle_message(self, sender_id: str, recipient_id: str, 
                            message: dict, background_task) -> None:
        """Handle incoming message"""
        message_text = ""
        
        if message.get("text"):
            message_text = message["text"]["body"]
        elif message.get("audio"):
            # TODO: Process audio with audio processing agent
            audio_id = message["audio"]["id"]
            logger.info(f"Audio message received: {audio_id}")
            message_text = "[Audio message - processing...]"
        elif message.get("image"):
            # TODO: Process image with media processing agent
            image_id = message["image"]["id"]
            logger.info(f"Image message received: {image_id}")
            message_text = "[Image message - processing...]"
        elif message.get("document"):
            # TODO: Process document with media processing agent
            doc_id = message["document"]["id"]
            logger.info(f"Document message received: {doc_id}")
            message_text = "[Document message - processing...]"

        if not message_text:
            return

        # Create request structure
        request = UserRequest(
            user_id=sender_id,
            vendor_id=recipient_id,
            message=message_text,
            session_id=f"whatsapp-{sender_id}-{recipient_id}"
        )

        # Get response from chat interface
        response = await self.get_response(request, background_task)
        
        # Send response
        self.send_message(recipient_id, sender_id, response)

    async def get_response(self, request: Union[UserRequest, BusinessRequest], 
                          background_task) -> str:
        """Get response from appropriate agent"""
        try:
            from backend.chatbot.agents.user_chat_interface import chat
            from backend.chatbot.agents.business_chat_interface import business_chat

            if isinstance(request, UserRequest):
                response = await chat(request, background_task, reset_user_state=False)
            elif isinstance(request, BusinessRequest):
                response = await business_chat(request, background_task)
            else:
                raise ValueError(f"Unsupported request type: {type(request)}")

            logger.info(f"Response generated: {response[:100]}...")
            return response
        except Exception as e:
            logger.error(f"Error getting response: {e}")
            return "Sorry, I encountered an error. Please try again."

    def send_message(self, phone_number_id: str, recipient_id: str, message: str) -> bool:
        """Send WhatsApp message"""
        if not self.page_access_token or not phone_number_id:
            logger.warning("WhatsApp credentials not configured")
            return False

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_id,
            "type": "text",
            "text": {
                "preview_url": True,
                "body": message,
            },
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.page_access_token}",
        }

        try:
            response = requests.post(
                f"https://graph.facebook.com/v18.0/{phone_number_id}/messages",
                json=payload,
                headers=headers,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to send message: {response.status_code} - {response.text}")
                return False
            else:
                logger.info(f"Message sent successfully to {recipient_id}")
                return True
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False

    def verify_signature(self, request_body: bytes, signature: str) -> bool:
        """Verify webhook signature"""
        if not self.app_secret:
            logger.warning("APP_SECRET not configured, skipping signature verification")
            return True  # Allow in development
        
        if signature.startswith("sha256="):
            sha256 = hmac.new(
                self.app_secret.encode("utf-8"),
                request_body,
                hashlib.sha256
            ).hexdigest()
            return sha256 == signature[7:]
        elif signature.startswith("sha1="):
            sha1 = hmac.new(
                self.app_secret.encode("utf-8"),
                request_body,
                hashlib.sha1
            ).hexdigest()
            return sha1 == signature[5:]
        return False


# Create singleton instance
whatsapp = WhatsappBot()
