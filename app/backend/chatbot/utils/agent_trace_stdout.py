"""Human-readable traces to stdout (e.g. docker-compose logs)."""

from __future__ import annotations

from typing import Any, List


def agent_stdout(tag: str, body: str, max_len: int = 14000) -> None:
    b = (body or "").strip()
    if len(b) > max_len:
        b = b[: max_len - 24] + "\n... [truncated]"
    print(f"\n{'=' * 16} {tag} {'=' * 16}\n{b}\n", flush=True)


def format_message_history_for_stdout(history: Any, *, max_turns: int = 60) -> str:
    """Pretty lines for pydantic_ai message objects or JSON dicts in Redis chat_history."""
    if not history:
        return "(empty chat_history)"
    lines: List[str] = []
    hist = list(history)
    tail = hist[-max_turns:] if len(hist) > max_turns else hist
    if len(hist) > max_turns:
        lines.append(f"... ({len(hist) - max_turns} older turns omitted, showing last {max_turns})")
    offset = len(hist) - len(tail)
    for j, m in enumerate(tail):
        i = offset + j
        try:
            if hasattr(m, "parts"):
                bits = []
                for p in m.parts:
                    c = getattr(p, "content", None)
                    if c is not None:
                        bits.append(f"{type(p).__name__}:{repr(c)[:900]}")
                    else:
                        bits.append(type(p).__name__)
                lines.append(f"[{i}] {type(m).__name__} → " + " | ".join(bits))
            elif isinstance(m, dict):
                lines.append(f"[{i}] dict {str(m)[:900]}")
            else:
                lines.append(f"[{i}] {repr(m)[:900]}")
        except Exception as ex:  # noqa: BLE001
            lines.append(f"[{i}] <serialize error: {ex}>")
    return "\n".join(lines)
