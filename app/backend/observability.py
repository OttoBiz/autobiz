"""Logfire setup for the Ottobiz backend.

Single entry point — production (`app/main.py`), the smoke CLI (`cli/cli.py`),
and the TUI (`cli/tui.py`) all call `setup()` before importing the agent
package. Importers that haven't run setup (typically unit tests) get logfire
warnings suppressed via `LOGFIRE_IGNORE_NO_CONFIG=1` in the agent modules.

Idempotent: re-calling `setup()` is a no-op so re-imports don't double-
instrument pydantic-ai.
"""

from __future__ import annotations

import os

_INSTRUMENTED = False


def setup() -> None:
    """Configure logfire and instrument pydantic-ai.

    Honors environment:
    - `LOGFIRE_CONSOLE=0`  : suppress console output (TUI sets this so spans
                             don't clobber the RichLog layout).
    - `LOGFIRE_TOKEN`      : enables remote send when present; without it
                             logfire still runs locally for stdlib logging.
    """
    global _INSTRUMENTED
    if _INSTRUMENTED:
        return

    try:
        import logfire
    except ImportError:
        # logfire is optional at runtime — agents fall back to stdlib logging
        # when it isn't installed.
        _INSTRUMENTED = True
        return

    console_disabled = os.environ.get("LOGFIRE_CONSOLE", "1") == "0"
    logfire.configure(
        send_to_logfire="if-token-present",
        console=False if console_disabled else None,
        scrubbing=False,
    )
    logfire.instrument_pydantic_ai()
    # WhatsappBot uses sync `requests` to hit Graph; without this every
    # outbound send is invisible to traces. Surface the failure rather than
    # swallow — a missing instrumentation dep should be a visible warning,
    # not a silent observability hole.
    try:
        logfire.instrument_requests()
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            "logfire.instrument_requests() failed: %s — graph.facebook.com calls "
            "will not produce HTTP spans. Install opentelemetry-instrumentation-requests.",
            exc,
        )

    _INSTRUMENTED = True
