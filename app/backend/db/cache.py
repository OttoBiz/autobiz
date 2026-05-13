import json

# from .models import Chat
# from dotenv import load_dotenv
import os
from datetime import date, datetime
from decimal import Decimal
from typing import List, Union
from uuid import UUID

from pydantic import BaseModel as PydanticBaseModel

from redis import Redis
from redis.cluster import RedisCluster

# load_dotenv()
DEBUG = os.getenv("DEBUG")
REDIS_URL = os.getenv("REDIS_URL")


class JSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles UUID, Decimal, and datetime types"""

    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, PydanticBaseModel):
            return obj.model_dump(mode="json")
        return super().default(obj)


class Cache:
    def __init__(self, host, port, password):
        if DEBUG == "true":
            self._client = Redis(
                host=host, port=port, password=password, decode_responses=True
            )
        else:
            if REDIS_URL:
                self._client = Redis.from_url(REDIS_URL)
            else:
                self._client = RedisCluster(
                    host=host, port=port, password=password, decode_responses=True
                )

    def set(self, key: str, val: dict) -> None:
        self._client.set(key, json.dumps(val, cls=JSONEncoder))

    def get(self, key: str) -> dict:
        value = self._client.get(key)
        if value:
            return json.loads(value)
        else:
            return {}

    def get_chat_history(self, session_id: str) -> Union[List]:  # List[Chat],
        chat_history = self._client.get(session_id)
        if chat_history:
            return json.loads(chat_history)
        else:
            return None

    def set_chat_history(
        self, session_id: str, chat_history: Union[List]
    ) -> None:  # List[Chat],
        return self._client.set(session_id, json.dumps(chat_history, cls=JSONEncoder))

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def push_to_list(self, key: str, value: dict) -> None:
        self._client.rpush(key, json.dumps(value, cls=JSONEncoder))

    def rpush_json_capped(self, key: str, value: dict, max_items: int) -> None:
        """Append JSON value and trim list to the last ``max_items`` entries."""
        if max_items < 1:
            return
        payload = json.dumps(value, cls=JSONEncoder)
        pipe = self._client.pipeline()
        pipe.rpush(key, payload)
        pipe.ltrim(key, -max_items, -1)
        pipe.execute()

    def list_tail_json(self, key: str, count: int) -> List[dict]:
        """Last ``count`` list elements as parsed JSON (oldest-first within the window)."""
        if count <= 0:
            return []
        items = self._client.lrange(key, -count, -1)
        out: List[dict] = []
        for item in items:
            try:
                out.append(json.loads(item))
            except (json.JSONDecodeError, TypeError):
                continue
        return out

    def pop_all_from_list(self, key: str) -> list:
        items = self._client.lrange(key, 0, -1)
        self._client.delete(key)
        return [json.loads(item) for item in items]

    def flush_db(self):
        self._client.flushdb()
