from .cache import Cache
from .config import (
    REDIS_SERVER_HOST,
    REDIS_SERVER_PORT,
    REDIS_SERVER_PASSWORD
)


from typing import List

redis_conn = Cache(
    host=REDIS_SERVER_HOST,
    port=REDIS_SERVER_PORT,
    password=REDIS_SERVER_PASSWORD
)


async def get_user_state(user_id, vendor_id, session_id= None):
    user_state = redis_conn.get(f"{user_id}:{vendor_id}")

    # chat_history = redis_conn.get_chat_history(f"{user_id}:{vendor_id}") or []
    return user_state #, chat_history



async def modify_user_state(user_id, vendor_id, user_state,  session_id=None):
    # Rewrite history to redis.
    redis_conn.set(f"{user_id}:{vendor_id}", user_state)
    # redis_conn.set_chat_history(session_id, chat_history)

    return