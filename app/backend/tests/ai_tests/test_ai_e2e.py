"""
Parametrized AI E2E tests: each scenario × history mode (fresh, short, long, mixed_prior_products).

Run from repository `app` folder:

    pytest backend/tests/ai_tests/test_ai_e2e.py -v -m ai_e2e

With Docker backend on another host:

    set AUTOBIZ_BASE_URL=http://192.168.1.10:8000
    pytest backend/tests/ai_tests/test_ai_e2e.py -m ai_e2e -k "fresh and product_available"
"""

from __future__ import annotations

import pytest

from .harness import run_scenario
from .scenarios import SCENARIOS

HISTORY_MODES = ["fresh", "short", "long", "mixed_prior_products"]


@pytest.mark.ai_e2e
@pytest.mark.asyncio
@pytest.mark.parametrize("history_mode", HISTORY_MODES)
@pytest.mark.parametrize(
    "scenario",
    SCENARIOS,
    ids=[s.id for s in SCENARIOS],
)
async def test_ai_conversation_scenario(api_client, scenario, history_mode):
    result = await run_scenario(api_client, scenario, history_mode)
    if result.error:
        pytest.fail(
            f"Harness error: {result.error}\n\nTranscript:\n{result.transcript}"
        )
    assert result.passed, (
        f"Judge failed (confidence={result.judge_confidence}): {result.judge_reasoning}\n\n"
        f"Transcript:\n{result.transcript}"
    )
