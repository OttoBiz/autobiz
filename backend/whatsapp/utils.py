import hashlib
import hmac
import json
import os
from typing import Union
from urllib.parse import parse_qs
from pydantic import BaseModel
import requests

from dotenv import load_dotenv
import logging


load_dotenv()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
APP_SECRET = os.getenv("APP_SECRET")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MessageRequest(BaseModel):
    message: str


class UserRequest(BaseModel):
    user_id: str
    vendor_id: str
    message: str


class BusinessRequest(BaseModel):
    sender: str
    message: str
    product_name: str
    product_price: str
    user_id: str
    vendor_id: str
    logistic_id: str
    message_type: str


class WhatsappBot:
    def __init__(self, page_access_token, app_secret, verify_token):
        self.page_access_token = page_access_token
        self.app_secret = app_secret
        self.verify_token = verify_token

    def verify_webhook(self, request):
        query_params = parse_qs(str(request.query_params))
        mode = query_params.get("hub.mode", None)
        token = query_params.get("hub.verify_token", None)
        challenge = query_params.get("hub.challenge", None)

        if mode and token:
            if mode[0] == "subscribe" and token[0] == self.verify_token:
                return challenge[0]
            else:
                return "Invalid verification token"

    async def handle_webhook(self, request, background_task):
        if request.method == "POST":
            body = await request.body()
            signature = request.headers.get("X-Hub-Signature", "")

            if not self.verify_signature(body, signature):
                return "Invalid signature", 403

            data = json.loads(body)

            entry = data["entry"][0]
            messaging_events = [
                changes.get("value")
                for changes in entry.get("changes", [])
                if changes.get("value")
            ]

            if messaging_events[0].get("statuses"):
                return "OK"

            # for event in messaging_events:
            recipient_id = messaging_events[0]["metadata"]["display_phone_number"]
            phone_number_id = messaging_events[0]["metadata"]["phone_number_id"]
            message = messaging_events[0]["messages"][0]
            sender_id = message["from"]
            await self.handle_message(sender_id, phone_number_id, message, background_task)
        return "OK"

    def process_audio(self, audio):
        pass

    async def handle_message(self, sender_id, recipient_id, message, background_task):
        message_text = ""
        if message.get("text"):
            message_text = message["text"]["body"]
        elif message.get("audio"):
            audio_id = message["audio"]["id"]
            self.process_audio(audio_id)
            # todo: process audio messages in the future

        # Create structure for message
        request = UserRequest(user_id=sender_id, vendor_id="2349027728309", message=message_text)

        response = await self.get_response(request=request, background_task=background_task)
        self.send_message(recipient_id, sender_id, response)

    async def get_response(self, request: Union[UserRequest, BusinessRequest], background_task) -> str:
        from backend.chatbot.agents.user_chat_interface import chat
        from backend.chatbot.agents.business_chat_interface import business_chat

        if isinstance(request, UserRequest):
            response = await chat(request, background_task)
        elif isinstance(request, BusinessRequest):
            response = await business_chat(request, background_task)
        else:
            raise ValueError(f"Unsupported request type: {type(request)}")

        logger.info(f"Message: {response}")
        return response

    def send_message(self, phone_number_id, recipient_id, message):
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

        response = requests.post(
            f"https://graph.facebook.com/v15.0/{phone_number_id}/messages",
            json=payload,
            headers=headers,
        )
        if response.status_code != 200:
            logging.error(response.text)
            logging.error(f"Failed to send message: {response.status_code}")
            return "Failed to send message:", response.status_code
        else:
            logging.info(f"Message sent to {recipient_id}")
            return "Message sent to", recipient_id

    def verify_signature(self, request_body, signature):
        if signature.startswith("sha1="):
            sha1 = hmac.new(
                self.app_secret.encode("utf-8"), request_body, hashlib.sha1
            ).hexdigest()
            return sha1 == signature[5:]
        else:
            return False


whatsapp = WhatsappBot(PAGE_ACCESS_TOKEN, APP_SECRET, VERIFY_TOKEN)