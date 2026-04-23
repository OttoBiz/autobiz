"""Scripted smoke scenarios.

Each scenario drives the orchestrator + outbound paths headlessly so CI can
exercise full conversation flows without spinning up the TUI. Populated in
task #9; this file currently exposes the registration shape only.
"""

from __future__ import annotations

from typing import Awaitable, Callable

ScenarioFn = Callable[[], Awaitable[int]]

_REGISTRY: dict[str, ScenarioFn] = {}


def register(name: str, fn: ScenarioFn) -> None:
    _REGISTRY[name] = fn


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
        print(f"✗ Unknown scenario {name!r}. Available: {', '.join(_REGISTRY) or '(none yet)'}")
        return 2
    return await _REGISTRY[name]()
