from backend.logging_config import get_logger
from pydantic_ai.messages import ModelMessagesTypeAdapter

from .cache import Cache
from .config import REDIS_SERVER_HOST, REDIS_SERVER_PASSWORD, REDIS_SERVER_PORT

logger = get_logger(__name__)

redis_conn = Cache(
    host=REDIS_SERVER_HOST, port=REDIS_SERVER_PORT, password=REDIS_SERVER_PASSWORD
)


async def get_user_state(user_id, vendor_id, session_id=None):
    try:
        user_state = redis_conn.get(f"{user_id}:{vendor_id}")
        if user_state and "chat_history" in user_state:
            raw = user_state["chat_history"]
            if raw and isinstance(raw[0], dict):
                try:
                    user_state["chat_history"] = ModelMessagesTypeAdapter.validate_python(raw)
                except Exception:
                    user_state["chat_history"] = []
        return user_state
    except Exception:
        logger.error(
            "redis_get_failed | user_id=%s vendor_id=%s",
            user_id,
            vendor_id,
            exc_info=True,
        )
        return {}


def _serialize_user_state(user_state: dict) -> dict:
    """Convert user_state to JSON-serializable form (chat_history may contain pydantic_ai objects)."""
    state = dict(user_state)
    chat_history = state.get("chat_history")
    if chat_history and any(not isinstance(m, dict) for m in chat_history):
        state["chat_history"] = ModelMessagesTypeAdapter.dump_python(chat_history, mode="json")
    return state


async def modify_user_state(user_id, vendor_id, user_state, session_id=None):
    try:
        serializable = _serialize_user_state(user_state)
        redis_conn.set(f"{user_id}:{vendor_id}", serializable)
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
