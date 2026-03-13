from backend.logging_config import get_logger

from .cache import Cache
from .config import REDIS_SERVER_HOST, REDIS_SERVER_PASSWORD, REDIS_SERVER_PORT

logger = get_logger(__name__)

redis_conn = Cache(
    host=REDIS_SERVER_HOST, port=REDIS_SERVER_PORT, password=REDIS_SERVER_PASSWORD
)


async def get_user_state(user_id, vendor_id, session_id=None):
    try:
        user_state = redis_conn.get(f"{user_id}:{vendor_id}")
        return user_state
    except Exception:
        logger.error(
            "redis_get_failed | user_id=%s vendor_id=%s",
            user_id,
            vendor_id,
            exc_info=True,
        )
        return {}


async def modify_user_state(user_id, vendor_id, user_state, session_id=None):
    try:
        redis_conn.set(f"{user_id}:{vendor_id}", user_state)
    except Exception:
        logger.error(
            "redis_set_failed | user_id=%s vendor_id=%s",
            user_id,
            vendor_id,
            exc_info=True,
        )


async def delete_user_state(user_id, vendor_id):
    try:
        redis_conn.delete(f"{user_id}:{vendor_id}")
    except Exception:
        logger.error(
            "redis_delete_failed | user_id=%s vendor_id=%s",
            user_id,
            vendor_id,
            exc_info=True,
        )


async def push_to_inbox(recipient_id: str, message: dict) -> None:
    try:
        redis_conn.push_to_list(f"inbox:{recipient_id}", message)
    except Exception:
        logger.error("inbox_push_failed | recipient_id=%s", recipient_id, exc_info=True)


async def get_inbox(recipient_id: str) -> list:
    try:
        return redis_conn.pop_all_from_list(f"inbox:{recipient_id}")
    except Exception:
        logger.error("inbox_get_failed | recipient_id=%s", recipient_id, exc_info=True)
        return []
