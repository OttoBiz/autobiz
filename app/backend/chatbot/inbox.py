import json
from datetime import datetime, timezone

from backend.db.cache import JSONEncoder
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
    key = _inbox_key(business_id, customer_id)
    client = redis_conn._client
    pipe = client.pipeline(transaction=True)
    pipe.rpush(key, json.dumps(item, cls=JSONEncoder))
    pipe.expire(key, INBOX_TTL_SECONDS)
    pipe.execute()


def drain(business_id: str, customer_id: str) -> list[dict]:
    key = _inbox_key(business_id, customer_id)
    client = redis_conn._client
    pipe = client.pipeline(transaction=True)
    pipe.lrange(key, 0, -1)
    pipe.delete(key)
    items, _ = pipe.execute()
    return [json.loads(item) for item in items]


def peek(business_id: str, customer_id: str) -> list[dict]:
    key = _inbox_key(business_id, customer_id)
    items = redis_conn._client.lrange(key, 0, -1)
    return [json.loads(item) for item in items]


def acquire_lock(
    business_id: str,
    customer_id: str,
    owner: str,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
) -> bool:
    """Per-customer mutex. central_agent (orchestrator) and coordinator (resolution router) must serialize on it."""
    key = _lock_key(business_id, customer_id)
    return bool(redis_conn._client.set(key, owner, nx=True, ex=ttl_seconds))


def release_lock(business_id: str, customer_id: str, owner: str) -> bool:
    key = _lock_key(business_id, customer_id)
    client = redis_conn._client
    # Owner check + delete must be atomic so we never delete a lock that has
    # already expired and been re-acquired by someone else.
    with client.pipeline(transaction=True) as pipe:
        while True:
            try:
                pipe.watch(key)
                current = pipe.get(key)
                # The redis client may be configured with decode_responses=True
                # (returns str) or False (returns bytes). Normalize before
                # comparing — without this, every release_lock returned False
                # because b"abc" != "abc", so locks lived until TTL expiry
                # (60s) and back-to-back customer turns silently dropped.
                if isinstance(current, bytes):
                    current = current.decode()
                if current != owner:
                    pipe.unwatch()
                    return False
                pipe.multi()
                pipe.delete(key)
                pipe.execute()
                return True
            except Exception:
                continue


def get_cursor(business_id: str, customer_id: str) -> datetime | None:
    raw = redis_conn._client.get(_cursor_key(business_id, customer_id))
    if not raw:
        return None
    return datetime.fromisoformat(raw)


def set_cursor(business_id: str, customer_id: str, ts: datetime) -> None:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    redis_conn._client.set(_cursor_key(business_id, customer_id), ts.isoformat())
