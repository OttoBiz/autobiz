"""Logging handler that pushes records onto an asyncio.Queue.

Used by the TUI's System tab to surface orchestrator/outbound/coordinator
events without re-instrumenting every module. Plug it into the root logger
once at startup and the System pane is fed for free.
"""

from __future__ import annotations

import asyncio
import logging
from typing import ClassVar


class QueueLogHandler(logging.Handler):
    """Forward log records as formatted strings into an asyncio.Queue.

    The handler runs on the calling thread (which may not be the event-loop
    thread for certain log paths). To stay safe we use
    `loop.call_soon_threadsafe` to enqueue.
    """

    DEFAULT_FORMAT: ClassVar[str] = "%(asctime)s %(levelname)s %(name)s | %(message)s"

    def __init__(self, queue: asyncio.Queue[str], loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.queue = queue
        self.loop = loop
        self.setFormatter(logging.Formatter(self.DEFAULT_FORMAT, "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            self.handleError(record)
            return
        try:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, line)
        except RuntimeError:
            # Event loop closed during shutdown; drop the record.
            pass


def install(
    queue: asyncio.Queue[str],
    loop: asyncio.AbstractEventLoop,
    level: int = logging.INFO,
    loggers: tuple[str, ...] = (
        "backend.chatbot",
        "backend.chatbot.conversations.inbox",
        "backend.chatbot.conversations.conversation",
        "backend.chatbot.sweeper",
    ),
) -> QueueLogHandler:
    """Attach the queue handler to the chatbot loggers. Returns the handler
    so callers can `removeHandler` on shutdown."""
    handler = QueueLogHandler(queue, loop)
    handler.setLevel(level)
    for name in loggers:
        log = logging.getLogger(name)
        log.addHandler(handler)
        # Lift the level if it's stricter than what we want to see.
        if log.level == logging.NOTSET or log.level > level:
            log.setLevel(level)
    return handler
