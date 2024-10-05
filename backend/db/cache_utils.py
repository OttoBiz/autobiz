from .cache import Cache
from .config import (
    REDIS_SERVER_HOST,
    REDIS_SERVER_PORT,
    REDIS_SERVER_PASSWORD,
    REDIS_URL
)


from typing import Optional

redis_conn = Cache(
    url=REDIS_URL,
    host=REDIS_SERVER_HOST,
    port=REDIS_SERVER_PORT,
    password=REDIS_SERVER_PASSWORD
)


def test_redis_connection():
    if redis_conn.ping():
        print("Successfully connected to Redis!")
    else:
        print("Failed to connect to Redis.")


async def get_user_state(user_id: str, vendor_id: str, session_id: Optional[str] = None) -> dict:
    key = f"user_state:{user_id}:{vendor_id}"
    user_state = redis_conn.get(key)
    return user_state or {}

async def modify_user_state(user_id: str, vendor_id: str, user_state: dict, session_id: Optional[str] = None) -> None:
    key = f"user_state:{user_id}:{vendor_id}"
    redis_conn.set(key, user_state)

async def delete_user_state(user_id: str, vendor_id: str) -> None:
    key = f"user_state:{user_id}:{vendor_id}"
    redis_conn.delete(key)


test_redis_connection()