"""Probe the /webhooks/whatsapp and /webhooks/http endpoints in-process.

Runs the real FastAPI app from app/main.py, but stubs out the database
lifecycle and the orchestrator so we can verify endpoint wiring (parsing,
routing, registry lookup, response shape) without touching Postgres or
spending LLM tokens.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

REPO = Path(__file__).resolve().parents[1]
APP_DIR = REPO / "app"
sys.path.insert(0, str(APP_DIR))


def main() -> int:
    # 1. Stub db lifecycle and sweeper so startup() returns instantly.
    import backend.db.connection as db_conn
    import backend.db.populate as db_pop
    import backend.chatbot.sweeper as sweeper

    db_conn.init_db = AsyncMock(return_value=None)
    db_conn.close_db = AsyncMock(return_value=None)
    db_pop.populate_db_on_startup = AsyncMock(return_value=None)

    async def _noop_sweep_loop():
        return None

    sweeper.sweep_loop = _noop_sweep_loop

    # 2. Stub the orchestrator so we can confirm it was called with the
    #    parsed message but don't actually invoke any agents.
    from backend.chatbot import orchestrator
    handled: list = []

    async def _record(msg):
        handled.append(msg)

    orchestrator.handle_inbound = _record

    # 3. Re-import the routers AFTER patching, since they captured the
    #    original handle_inbound at import time.
    from backend.api.routers.webhooks import http as http_router
    from backend.api.routers.webhooks import whatsapp as whatsapp_router

    http_router.orchestrator = orchestrator
    whatsapp_router.orchestrator = orchestrator

    # 4. Import the app and use TestClient to exercise the routes.
    from fastapi.testclient import TestClient
    import main as app_main

    results: dict[str, dict] = {}

    with TestClient(app_main.app) as client:
        # --- Health probe (sanity) ---
        r = client.get("/health")
        results["GET /health"] = {
            "status": r.status_code,
            "body": r.json() if r.status_code == 200 else r.text,
        }

        # --- WhatsApp verify (GET handshake) ---
        r = client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "test-token",
                "hub.challenge": "12345",
            },
        )
        results["GET /webhooks/whatsapp"] = {
            "status": r.status_code,
            "body": r.text[:200],
        }

        # --- WhatsApp inbound (POST) ---
        wa_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_ID",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "15555550100",
                                    "phone_number_id": "PNID",
                                },
                                "contacts": [
                                    {
                                        "profile": {"name": "Probe User"},
                                        "wa_id": "15555550999",
                                    }
                                ],
                                "messages": [
                                    {
                                        "from": "15555550999",
                                        "id": "wamid.PROBE",
                                        "timestamp": "1700000000",
                                        "type": "text",
                                        "text": {"body": "hello from probe"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
        r = client.post("/webhooks/whatsapp", json=wa_payload)
        results["POST /webhooks/whatsapp"] = {
            "status": r.status_code,
            "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text,
            "handled_count": len(handled),
            "last_handled_text": getattr(handled[-1], "text", None) if handled else None,
            "last_handled_channel": getattr(handled[-1], "channel", None) if handled else None,
        }

        # --- HTTP webhook inbound (POST) ---
        before = len(handled)
        http_payload = {
            "business_id": "biz-probe",
            "customer_id": "probe-user-1",
            "channel_user_id": "probe-user-1",
            "text": "hello via http",
        }
        r = client.post("/webhooks/http", json=http_payload)
        results["POST /webhooks/http"] = {
            "status": r.status_code,
            "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text,
            "handled_count": len(handled) - before,
            "last_handled_text": getattr(handled[-1], "text", None) if handled else None,
            "last_handled_channel": getattr(handled[-1], "channel", None) if handled else None,
        }

    print(json.dumps(results, indent=2, default=str))
    failures = [k for k, v in results.items() if v.get("status") != 200]
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
