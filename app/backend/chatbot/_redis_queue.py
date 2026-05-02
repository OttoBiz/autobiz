"""Generic per-key Redis queue + mutex primitives.

Underpins both `chatbot/inbox.py` (per-customer turn queue) and
`chatbot/contact_inbox.py` (per-contact debounced inbound). The two used
to copy-paste this code; centralized here so locks and TTLs behave
identically and future bug fixes land in one place.

Naming: callers compute their own composite keys (e.g.
`f"inbox:{biz}:{cust}"`, `f"contact_inbox:{biz}:{contact}"`) and pass
them in. This module is namespace-agnostic by design.
"""

from __future__ import annotations

import json
from typing import Any

from backend.db.cache import JSONEncoder
from backend.db.cache_utils import redis_conn


# ---------------------------------------------------------------------------
# Queue: rpush / lrange / delete with TTL refresh on every push.
# ---------------------------------------------------------------------------


def push(key: str, item: Any, *, ttl_seconds: int) -> None:
    """Append `item` to the list at `key`, refresh TTL.

    `item` is JSON-serialized via the project-wide JSONEncoder so UUIDs and
    datetimes survive round-trips. Use `pop_all` / `peek` to read, `clear`
    to drop the queue.
    """
    client = redis_conn._client
    pipe = client.pipeline(transaction=True)
    pipe.rpush(key, json.dumps(item, cls=JSONEncoder))
    pipe.expire(key, ttl_seconds)
    pipe.execute()


def peek(key: str) -> list[Any]:
    """Return all queued items without modifying the list."""
    raw = redis_conn._client.lrange(key, 0, -1)
    out: list[Any] = []
    for item in raw:
        try:
            out.append(json.loads(item))
        except (ValueError, TypeError):
            # Tolerate corrupt entries — drop them silently rather than
            # crash the whole drain.
            continue
    return out


def pop_all(key: str) -> list[Any]:
    """Atomically read every item and clear the list."""
    client = redis_conn._client
    pipe = client.pipeline(transaction=True)
    pipe.lrange(key, 0, -1)
    pipe.delete(key)
    items, _ = pipe.execute()
    out: list[Any] = []
    for item in items:
        try:
            out.append(json.loads(item))
        except (ValueError, TypeError):
            continue
    return out


def clear(key: str) -> None:
    """Drop the queue without reading. Idempotent."""
    redis_conn._client.delete(key)


# ---------------------------------------------------------------------------
# Dedup + token-aware drain: SET NX dedup keys, peek with raw tokens,
# remove specific entries by exact-match LREM.
# ---------------------------------------------------------------------------


def set_if_absent(key: str, value: str, ttl_seconds: int) -> bool:
    """SET NX with TTL. Returns True if the key was set, False if it already existed.

    Used as the dedup primitive: ingest() calls set_if_absent(dedup_key, "1", ttl)
    and drops the message if it returns False (Meta retry of a message we already
    enqueued).
    """
    return bool(redis_conn._client.set(key, value, nx=True, ex=ttl_seconds))


def peek_with_tokens(key: str) -> list[tuple[str, Any]]:
    """Return [(raw_json, parsed_dict), ...] without modifying the list.

    The raw_json string is the exact bytes stored in Redis — pass it back to
    drain_specific to LREM that exact entry. Parsed dict is the JSON-decoded
    form for application use. Corrupt entries are skipped silently (parity with
    peek()).
    """
    raw = redis_conn._client.lrange(key, 0, -1)
    out: list[tuple[str, Any]] = []
    for item in raw:
        # The redis client may be configured with decode_responses=True
        # (returns str) or False (returns bytes). Normalize before parsing.
        token = item.decode() if isinstance(item, bytes) else item
        try:
            parsed = json.loads(token)
        except (ValueError, TypeError):
            continue
        out.append((token, parsed))
    return out


def drain_specific(key: str, raw_tokens: list[str]) -> int:
    """Remove specified entries from the list by exact-string match.

    Calls LREM count=1 for each token. Returns total entries removed. Items
    pushed during the agent run survive (they weren't in raw_tokens).
    """
    if not raw_tokens:
        return 0
    client = redis_conn._client
    pipe = client.pipeline(transaction=False)
    for token in raw_tokens:
        pipe.lrem(key, 1, token)
    results = pipe.execute()
    return sum(int(r or 0) for r in results)


# ---------------------------------------------------------------------------
# Mutex: SET NX with owner check on release.
# ---------------------------------------------------------------------------


def acquire_lock(key: str, owner: str, ttl_seconds: int) -> bool:
    return bool(redis_conn._client.set(key, owner, nx=True, ex=ttl_seconds))


def release_lock(key: str, owner: str) -> bool:
    """Atomic owner-check + delete via WATCH/MULTI.

    Returns True only if we held the lock and successfully released it.
    Returns False if the lock has expired and been re-acquired by someone
    else — never deletes another owner's lock.
    """
    client = redis_conn._client
    with client.pipeline(transaction=True) as pipe:
        while True:
            try:
                pipe.watch(key)
                current = pipe.get(key)
                # The redis client may be configured with decode_responses=True
                # (returns str) or False (returns bytes). Normalize before
                # comparing — without this every release returned False.
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
