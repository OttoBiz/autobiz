from cache import Cache
from config import REDIS_SERVER_HOST, REDIS_SERVER_PORT, REDIS_SERVER_PASSWORD

from typing import List

redis_conn = Cache(
    host=REDIS_SERVER_HOST, port=REDIS_SERVER_PORT, password=REDIS_SERVER_PASSWORD
)


def get_user_state(user_id, session_id):
    user_db = redis_conn.get(user_id)
    chat_history = redis_conn.get_chat_history(session_id) or []
    return user_db, chat_history


async def modify_user_state(user_id, session_id, user_db, user_params, chat_history):
    # Update user_db for now.
    user_db["user_params"] = user_params
    user_db["session_chat_history"] = chat_history

    # Rewrite history to redis.
    redis_conn.set(user_id, user_db)
    redis_conn.set_chat_history(session_id, chat_history)

    return
