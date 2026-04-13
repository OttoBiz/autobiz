"""
Summarize chat_history / communication_history when they exceed word limits.
Keeps the last N messages intact; older messages are collapsed into a summary.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from backend.chatbot.agents.base_agent import BaseAgent
from backend.config import (
    CHAT_HISTORY_KEEP_LAST_N,
    CHAT_HISTORY_SUMMARY_WORD_LIMIT,
    COMM_HISTORY_KEEP_LAST_N,
    COMM_HISTORY_SUMMARY_WORD_LIMIT,
)
from backend.logging_config import get_logger

logger = get_logger(__name__)

_summarizer = BaseAgent(
    system_prompt="Summarize the conversation below into a concise paragraph. "
    "Preserve every concrete fact (names, prices, order numbers, decisions, addresses). "
    "Omit greetings, filler, and repetition. Output only the summary text.",
)


def _extract_text(messages: list) -> str:
    lines = []
    for m in messages:
        if isinstance(m, dict):
            role = m.get("role") or m.get("name") or "unknown"
            lines.append(f"{role}: {m.get('content', '')}")
        else:
            role = "user" if getattr(m, "kind", None) == "request" else "assistant"
            parts = getattr(m, "parts", [])
            text = " ".join(getattr(p, "content", str(p)) for p in parts).strip()
            if text:
                lines.append(f"{role}: {text}")
    return "\n".join(lines)


def _word_count(messages: list) -> int:
    return len(_extract_text(messages).split())


async def _run_summary(text: str) -> str:
    try:
        result = await _summarizer.run(f"Summarize:\n\n{text}")
        return result.output or text
    except Exception:
        logger.warning("summarizer_failed", exc_info=True)
        return text


async def maybe_summarize_chat_history(
    chat_history: List,
    existing_summary: Optional[str] = None,
    word_limit: int = CHAT_HISTORY_SUMMARY_WORD_LIMIT,
    keep_last_n: int = CHAT_HISTORY_KEEP_LAST_N,
) -> tuple[List, Optional[str], int]:
    """
    Returns (trimmed_history, new_summary_or_None, messages_summarized_count).
    If no summarization needed, summary is None and count is 0.
    """
    if _word_count(chat_history) <= word_limit:
        return chat_history, None, 0

    if len(chat_history) <= keep_last_n:
        return chat_history, None, 0

    old = chat_history[:-keep_last_n]
    recent = chat_history[-keep_last_n:]

    old_text = _extract_text(old)
    if existing_summary:
        old_text = f"Previous summary:\n{existing_summary}\n\nNew messages:\n{old_text}"

    summary = await _run_summary(old_text)

    trimmed = [
        ModelRequest(parts=[UserPromptPart(content=f"[Conversation summary]\n{summary}")]),
    ] + recent

    return trimmed, summary, len(old)


async def maybe_summarize_comm_history(
    comm_history: List[Dict[str, Any]],
    word_limit: int = COMM_HISTORY_SUMMARY_WORD_LIMIT,
    keep_last_n: int = COMM_HISTORY_KEEP_LAST_N,
) -> List[Dict[str, Any]]:
    """Summarize older comm entries in-place; returns the (possibly trimmed) list."""
    if _word_count(comm_history) <= word_limit:
        return comm_history

    if len(comm_history) <= keep_last_n:
        return comm_history

    old = comm_history[:-keep_last_n]
    recent = comm_history[-keep_last_n:]

    old_text = _extract_text(old)
    summary = await _run_summary(old_text)

    return [{"role": "system", "name": "event_summary", "content": summary}] + recent
