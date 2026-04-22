"""Outbound task timeout sweeper.

Periodically flips expired outbound tasks to `timed_out` via the ledger and
fans out operator alerts for each key that transitioned. See
`ARCHITECTURE_DECISIONS.md` -> "Hardening" (timeout sweeper bullet).
"""

import asyncio
import logging

from backend.db import outbound_ledger

logger = logging.getLogger(__name__)
SWEEP_INTERVAL_SECONDS = 60


async def alert_operator(task_key: str, reason: str) -> None:
    # TODO: replace stub with dashboard/Slack/email alerting.
    logger.warning("operator alert: task=%s reason=%s", task_key, reason)


async def sweep_once() -> list[str]:
    timed_out = await outbound_ledger.sweep_timeouts()
    for task_key in timed_out:
        await alert_operator(task_key, reason="timeout")
    return timed_out


async def sweep_loop(interval_seconds: int = SWEEP_INTERVAL_SECONDS) -> None:
    while True:
        try:
            await sweep_once()
        except Exception:
            logger.exception("sweeper iteration failed")
        await asyncio.sleep(interval_seconds)
