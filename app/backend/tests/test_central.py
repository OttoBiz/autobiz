"""Tests for central agent guardrails.

No live model — we mock subagent `.run` to control timing. Tests target the
subagent timeout fallback wired into the `_handle_*` wrappers.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.chatbot.agents import central
from backend.chatbot.agents.deps import AgentDeps


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

    deps = AgentDeps(user_id="u", business_id="b")
    started = time.monotonic()
    result = await central._handle_product(deps, "anything")
    elapsed = time.monotonic() - started

    assert result == {"error": "subagent_timeout", "subagent": "product"}
    # Generous upper bound — guards against the wrapper accidentally hanging.
    assert elapsed < 1.0
