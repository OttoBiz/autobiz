"""Scripted smoke scenarios.

Each scenario drives the orchestrator + outbound paths headlessly so you can
exercise full conversation flows without spinning up the TUI. They hit the
**real** stack — orchestrator, central_agent, outbound_agent, the model API.
That means they need:

- Redis + Postgres up (`docker compose up redis postgres` from app/)
- A model provider API key in env (e.g. OPENAI_API_KEY)

Run from the repo root:

    .venv/bin/python -m tests.smoke.cli --scenario healthcheck
    .venv/bin/python -m tests.smoke.cli --scenario all
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable
from uuid import UUID, uuid4

from backend.chatbot import orchestrator
from backend.chatbot.channels import registry
from backend.chatbot.channels.base import ChannelIdentity, InboundMessage

from tests.smoke.console_channel import ConsoleChannel
from tests.smoke.seed import ensure_smoke_data

ScenarioFn = Callable[[], Awaitable[int]]
_REGISTRY: dict[str, ScenarioFn] = {}


def register(name: str, fn: ScenarioFn) -> None:
    _REGISTRY[name] = fn


def scenario(name: str) -> Callable[[ScenarioFn], ScenarioFn]:
    """Decorator: register a scenario by name."""
    def _wrap(fn: ScenarioFn) -> ScenarioFn:
        register(name, fn)
        return fn
    return _wrap


async def run(name: str) -> int:
    if name == "all":
        for scenario_name, fn in _REGISTRY.items():
            print(f"=== {scenario_name} ===")
            rc = await fn()
            if rc != 0:
                print(f"✗ {scenario_name} failed (rc={rc})")
                return rc
            print(f"✓ {scenario_name}")
        return 0
    if name not in _REGISTRY:
        print(
            f"✗ Unknown scenario {name!r}. Available: "
            f"{', '.join(_REGISTRY) or '(none)'}"
        )
        return 2
    return await _REGISTRY[name]()


# -- helpers ----------------------------------------------------------------


def _customer_inbound(business_id: UUID, customer_id: UUID, text: str) -> InboundMessage:
    customer_addr = f"customer-{str(customer_id)[:8]}"
    return InboundMessage(
        identity=ChannelIdentity(
            business_id=str(business_id),
            customer_id=str(customer_id),
            channel="console",
            channel_user_id=customer_addr,
            last_inbound_at=datetime.now(timezone.utc),
        ),
        text=text,
        media=[],
        raw={"source": "smoke_scenario"},
        received_at=datetime.now(timezone.utc),
    )


async def _wait_for_customer_reply(
    channel: ConsoleChannel, customer_addr: str, timeout: float = 30.0
) -> str | None:
    """Drain outbox until we see a customer-bound message; return its text."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            identity, text = await asyncio.wait_for(
                channel.outbox.get(), timeout=deadline - asyncio.get_event_loop().time()
            )
        except asyncio.TimeoutError:
            return None
        if identity.channel_user_id == customer_addr:
            return text
        # Vendor-bound messages are fine — drain and keep looking.
    return None


# -- scenarios --------------------------------------------------------------


@scenario("healthcheck")
async def healthcheck() -> int:
    """Single-turn sanity: customer sends 'hi', expect any reply within 30s.

    Proves the full stack runs end-to-end with a real model: orchestrator,
    central_agent.run, ConsoleChannel.send, message_history persistence.
    """
    business_id = uuid4()
    customer_id = uuid4()
    customer_addr = f"customer-{str(customer_id)[:8]}"
    channel: ConsoleChannel = registry.get("console")  # type: ignore[assignment]

    # Seed FK parents for the random UUIDs this scenario allocates. The CLI
    # already seeds the default 11111111.../22222222... pair, but each
    # scenario uses fresh UUIDs to avoid cross-run contamination.
    await ensure_smoke_data(str(business_id), str(customer_id))

    msg = _customer_inbound(business_id, customer_id, "Hi, are you there?")
    print(f"  → sending: {msg.text!r}")
    await orchestrator.handle_inbound(msg)

    reply = await _wait_for_customer_reply(channel, customer_addr, timeout=60)
    if reply is None:
        print("  ✗ no customer-bound reply in 60s")
        return 1
    print(f"  ← bot: {reply!r}")
    return 0
