"""
HTTP client for the deployed Autobiz API.
All communication goes through the real Docker app — no mocking.
"""
import asyncio
from typing import Optional

import httpx


class AutobizClient:
    """Async HTTP client wrapping all Autobiz API endpoints."""

    def __init__(self, base_url: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def health_check(self) -> bool:
        async with httpx.AsyncClient(timeout=10.0) as http:
            try:
                r = await http.get(f"{self.base_url}/health")
                return r.status_code == 200
            except Exception:
                return False

    async def customer_chat(
        self,
        user_id: str,
        vendor_id: str,
        session_id: str,
        message: str,
        receipt_bytes: Optional[bytes] = None,
        receipt_filename: Optional[str] = None,
    ) -> str:
        """Send a customer message, optionally attaching a payment receipt file."""
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            if receipt_bytes and receipt_filename:
                mime = "application/pdf" if receipt_filename.endswith(".pdf") else "text/plain"
                r = await http.post(
                    f"{self.base_url}/api/v1/customer/chat",
                    data={
                        "user_id": user_id,
                        "vendor_id": vendor_id,
                        "session_id": session_id,
                        "message": message,
                    },
                    files={"files": (receipt_filename, receipt_bytes, mime)},
                )
            else:
                r = await http.post(
                    f"{self.base_url}/api/v1/customer/chat",
                    json={
                        "user_id": user_id,
                        "vendor_id": vendor_id,
                        "session_id": session_id,
                        "message": message,
                    },
                )
            r.raise_for_status()
            data = r.json()
            return data.get("message") or ""

    async def business_chat(
        self,
        session_id: str,
        message: str,
        vendor_id: str = "",
        logistic_id: str = "",
        sender: str = "business",
        recent_inbox: Optional[list] = None,
    ) -> str:
        """Send a message from a vendor or logistics operator."""
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            r = await http.post(
                f"{self.base_url}/api/v1/business/chat",
                json={
                    "vendor_id": vendor_id,
                    "logistic_id": logistic_id,
                    "session_id": session_id,
                    "sender": sender,
                    "message": message,
                    "recent_inbox": recent_inbox or [],
                },
            )
            r.raise_for_status()
            return r.json().get("message") or ""

    async def get_customer_inbox(self, user_id: str) -> list:
        """Poll customer inbox for proactive messages from the system."""
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.get(f"{self.base_url}/api/v1/customer/inbox/{user_id}")
            r.raise_for_status()
            return r.json().get("messages") or []

    async def get_vendor_inbox(self, vendor_id: str) -> list:
        """Poll vendor inbox for messages from the central agent."""
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.get(f"{self.base_url}/api/v1/business/inbox/{vendor_id}")
            r.raise_for_status()
            return r.json().get("messages") or []

    async def poll_vendor_inbox(
        self,
        vendor_id: str,
        poll_interval: float = 3.0,
        max_polls: int = 20,
    ) -> list:
        """Poll vendor inbox repeatedly until messages appear or timeout."""
        for _ in range(max_polls):
            messages = await self.get_vendor_inbox(vendor_id)
            if messages:
                return messages
            await asyncio.sleep(poll_interval)
        return []
