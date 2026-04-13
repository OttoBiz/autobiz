"""HTTP client for the deployed Autobiz API (Docker or local uvicorn)."""

from __future__ import annotations

import io
import uuid
from typing import Any, Dict, List, Optional

import httpx

from .config import AUTOBIZ_BASE_URL, REQUEST_TIMEOUT_S


class AutobizApiClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or AUTOBIZ_BASE_URL).rstrip("/")
        self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> Dict[str, Any]:
        r = await self._client.get(f"{self.base_url}/health")
        r.raise_for_status()
        return r.json()

    async def session_clear(
        self,
        user_id: str | None = None,
        vendor_id: str | None = None,
        logistic_id: str | None = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if user_id:
            body["user_id"] = user_id
        if vendor_id:
            body["vendor_id"] = vendor_id
        if logistic_id:
            body["logistic_id"] = logistic_id
        r = await self._client.post(f"{self.base_url}/api/v1/session/clear", json=body)
        r.raise_for_status()
        return r.json()

    async def customer_chat_json(
        self,
        user_id: str,
        vendor_id: str,
        message: str,
        session_id: str,
    ) -> str:
        payload = {
            "user_id": user_id,
            "vendor_id": vendor_id,
            "session_id": session_id,
            "message": message,
        }
        r = await self._client.post(
            f"{self.base_url}/api/v1/customer/chat",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
        return str(data.get("message", ""))

    async def customer_chat_multipart(
        self,
        user_id: str,
        vendor_id: str,
        message: str,
        session_id: str,
        files: List[tuple[str, bytes, str]],
    ) -> str:
        data = {
            "user_id": user_id,
            "vendor_id": vendor_id,
            "session_id": session_id,
            "message": message,
        }
        mp: List[tuple[str, Any]] = []
        for filename, content, mime in files:
            mp.append(
                (
                    "files",
                    (filename, io.BytesIO(content), mime),
                )
            )
        r = await self._client.post(
            f"{self.base_url}/api/v1/customer/chat",
            data=data,
            files=mp,
        )
        r.raise_for_status()
        out = r.json()
        return str(out.get("message", ""))

    async def business_chat(
        self,
        business_id: str,
        message: str,
        session_id: str,
        sender: str = "business",
    ) -> str:
        payload = {
            "business_id": business_id,
            "session_id": session_id,
            "sender": sender,
            "message": message,
        }
        r = await self._client.post(
            f"{self.base_url}/api/v1/business/chat",
            json=payload,
        )
        r.raise_for_status()
        return str(r.json().get("message", ""))

    async def logistics_chat(
        self,
        business_id: str,
        message: str,
        session_id: str,
        sender: str = "logistics",
    ) -> str:
        payload = {
            "business_id": business_id,
            "session_id": session_id,
            "sender": sender,
            "message": message,
        }
        r = await self._client.post(
            f"{self.base_url}/api/v1/logistics/chat",
            json=payload,
        )
        r.raise_for_status()
        return str(r.json().get("message", ""))

    async def get_customer_inbox(self, user_id: str) -> List[Dict[str, Any]]:
        r = await self._client.get(f"{self.base_url}/api/v1/customer/inbox/{user_id}")
        r.raise_for_status()
        return list(r.json().get("messages") or [])

    async def get_vendor_inbox(self, vendor_id: str) -> List[Dict[str, Any]]:
        r = await self._client.get(f"{self.base_url}/api/v1/business/inbox/{vendor_id}")
        r.raise_for_status()
        return list(r.json().get("messages") or [])

    async def get_logistics_inbox(self, logistic_id: str) -> List[Dict[str, Any]]:
        r = await self._client.get(
            f"{self.base_url}/api/v1/logistics/inbox/{logistic_id}"
        )
        r.raise_for_status()
        return list(r.json().get("messages") or [])


def new_session_id(prefix: str = "ai-test") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
