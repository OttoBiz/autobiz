"""Conversation state management for multi-agent workflows.

This module handles:
- Conversation state persistence (Pydantic AI pattern)
- State snapshots for pause/resume workflows
- Redis integration for caching (optional)
"""

from agents.state.manager import StateManager
from agents.state.snapshots import StateSnapshot

__all__ = ["StateManager", "StateSnapshot"]
