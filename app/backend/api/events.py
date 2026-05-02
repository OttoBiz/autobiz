"""Inventory pub/sub side effects.

Fire-and-forget Redis publishes. Failures are logged at warning and
swallowed -- they must never fail the HTTP request.
"""
import json
from typing import Any
from uuid import UUID

from backend.db.cache_utils import redis_conn
from backend.logging_config import get_logger

logger = get_logger(__name__)


def _serialize(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    return value


def _publish(channel: str, payload: dict) -> None:
    try:
        body = json.dumps({k: _serialize(v) for k, v in payload.items()})
        # Reach into the Cache wrapper's underlying redis-py client; the wrapper
        # doesn't expose publish() directly. Private-attr access is intentional.
        redis_conn._client.publish(channel, body)
    except Exception:
        logger.warning("inventory_publish_failed | channel=%s", channel, exc_info=True)


def emit_stock_changed(business_id, *, product_id, new_qty: int, delta: int, actor_type: str) -> None:
    _publish(
        f"inventory.stock_changed.{business_id}",
        {"product_id": product_id, "new_qty": new_qty, "delta": delta, "actor_type": actor_type},
    )


def emit_discontinued(business_id, *, product_id) -> None:
    _publish(
        f"inventory.discontinued.{business_id}",
        {"product_id": product_id},
    )
