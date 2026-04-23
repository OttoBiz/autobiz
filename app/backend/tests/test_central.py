"""Tests for central agent guardrails.

No live model — we mock subagent `.run`. Covers the subagent timeout fallback.
Resolved outbound tasks are delivered via the inbox queue (see
`test_outbound_resolution.py`), not pulled from central, so there is no
polling tool to test here.
"""

from __future__ import annotations

import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "")

import asyncio  # noqa: E402
import time  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402

from backend.chatbot.agents import central  # noqa: E402
from backend.chatbot.agents.deps import AgentDeps  # noqa: E402


@pytest.mark.asyncio
async def test_handle_subagent_timeout(monkeypatch):
    # Tiny override keeps the test fast; the wrapper still exercises wait_for.
    monkeypatch.setattr(central, "SUBAGENT_TIMEOUT_SECONDS", 0.05)

    never_fires = asyncio.Event()

    class _StubAgent:
        async def run(self, prompt, deps):
            await never_fires.wait()
            return None  # pragma: no cover -- never reached

    import backend.chatbot.agents.product as product_mod

    monkeypatch.setattr(product_mod, "product_agent", _StubAgent())

    deps = AgentDeps(customer_id=uuid4(), business_id=uuid4())
    started = time.monotonic()
    result = await central._handle_product(deps, "anything")
    elapsed = time.monotonic() - started

    assert result == {"error": "subagent_timeout", "subagent": "product"}
    # Generous upper bound — guards against the wrapper accidentally hanging.
    assert elapsed < 1.0
