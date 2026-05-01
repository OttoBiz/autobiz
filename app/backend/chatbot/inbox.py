"""Per-customer turn inbox + lock + cursor.

The orchestrator drains this on every customer turn. Items are dicts
(`{type, payload, enqueued_at}`) — see `_user_message_item` and
`deliver_system_event` in chatbot/orchestrator.py.

Queue + lock primitives delegate to `_redis_queue` so the same code
serves the contact-side inbox in `chatbot/contact_inbox.py`.
"""

from datetime import datetime, timezone

from backend.chatbot import _redis_queue
from backend.db.cache_utils import redis_conn

INBOX_TTL_SECONDS = 24 * 60 * 60
DEFAULT_LOCK_TTL_SECONDS = 60


def _inbox_key(business_id: str, customer_id: str) -> str:
    return f"inbox:{business_id}:{customer_id}"


def _lock_key(business_id: str, customer_id: str) -> str:
    return f"lock:inbox:{business_id}:{customer_id}"


def _cursor_key(business_id: str, customer_id: str) -> str:
    return f"central_agent_cursor:{business_id}:{customer_id}"


def enqueue(business_id: str, customer_id: str, item: dict) -> None:
    _redis_queue.push(
        _inbox_key(business_id, customer_id), item, ttl_seconds=INBOX_TTL_SECONDS
    )


def drain(business_id: str, customer_id: str) -> list[dict]:
    return _redis_queue.pop_all(_inbox_key(business_id, customer_id))


def peek(business_id: str, customer_id: str) -> list[dict]:
    return _redis_queue.peek(_inbox_key(business_id, customer_id))


def acquire_lock(
    business_id: str,
    customer_id: str,
    owner: str,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
) -> bool:
    """Per-customer mutex. central_agent (orchestrator) and coordinator (resolution router) must serialize on it."""
    return _redis_queue.acquire_lock(
        _lock_key(business_id, customer_id), owner, ttl_seconds=ttl_seconds
    )


def release_lock(business_id: str, customer_id: str, owner: str) -> bool:
    return _redis_queue.release_lock(_lock_key(business_id, customer_id), owner)


# Cursor — separate concern from queue/lock; kept here because the
# orchestrator reads/writes it on the same per-customer turn boundary.


def get_cursor(business_id: str, customer_id: str) -> datetime | None:
    raw = redis_conn._client.get(_cursor_key(business_id, customer_id))
    if not raw:
        return None
    return datetime.fromisoformat(raw)


def set_cursor(business_id: str, customer_id: str, ts: datetime) -> None:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    redis_conn._client.set(_cursor_key(business_id, customer_id), ts.isoformat())
