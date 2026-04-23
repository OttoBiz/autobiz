"""Path setup + env bootstrap for smoke tests.

The backend package lives under app/, but smoke tests live at the repo root.
Inject app/ onto sys.path and pre-load app/.env so smoke tests pick up the
real REDIS_URL / DATABASE_URL the user's docker-compose is using.
"""

from __future__ import annotations

import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[2] / "app"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

# Load app/.env BEFORE backend.* imports so REDIS / DATABASE config is in env.
try:
    from dotenv import load_dotenv

    load_dotenv(_APP_DIR / ".env")
except ImportError:
    pass
