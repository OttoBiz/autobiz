"""Path setup for smoke tests.

The backend package lives under app/, but smoke tests live at the repo root.
Inject app/ onto sys.path so `from backend.* import ...` works without
requiring PYTHONPATH on the command line.
"""

from __future__ import annotations

import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[2] / "app"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
