"""
Centralized logging configuration for Ottobiz.

Usage:
    from backend.logging_config import setup_logging, get_logger

    setup_logging()  # Call once at app startup
    logger = get_logger(__name__)  # Per-module logger
"""

import logging
import os

LOG_FILE = os.getenv("LOG_FILE", "app.log")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s | %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configure root logger with file handler (INFO+) and console handler (WARNING+).

    Args:
        level: Minimum level for file handler. Console always starts at WARNING.
    """
    root = logging.getLogger()

    # Avoid duplicate handlers on repeated calls
    if root.handlers:
        return

    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT)

    # File handler — captures everything at `level` and above
    fh = logging.FileHandler(LOG_FILE)
    fh.setLevel(level)
    fh.setFormatter(formatter)
    root.addHandler(fh)

    # Console handler — only WARNING+ to keep terminal clean
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(formatter)
    root.addHandler(ch)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger for per-module use."""
    return logging.getLogger(name)
