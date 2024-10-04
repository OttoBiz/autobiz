from typing import List, Union

from redis.cluster import RedisCluster
from redis import Redis
# from .models import Chat
from dotenv import load_dotenv
import os
import json
from .config import REDIS_URL

load_dotenv()
DEBUG = os.getenv("DEBUG")


class Cache:
    def __init__(self, host, port, password):
        self._client = Redis.from_url(REDIS_URL)
        # if DEBUG == "true":
        #     self._client = Redis(
        #     host=host,
        #     port=port,
        #     password=password,
        #     decode_responses=True)
        # else:
        #     if REDIS_URL:
        #         self._client = Redis.from_url(REDIS_URL)
        #     else:
        #         self._client = RedisCluster(
        #             host=host,
        #             port=port,
        #             password=password,
        #             decode_responses=True)

    def set(self, key: str, val: dict) -> None: 
        self._client.set(key, json.dumps(val))

    def get(self, key: str) -> dict:
        value = self._client.get(key)
        if value:
            return json.loads(value)
        else:
            return {}

    def get_chat_history(self, session_id: str) -> Union[List]: #List[Chat],
        chat_history = self._client.get(session_id)
        if chat_history:
            return json.loads(chat_history)
        else:
            return None

    def set_chat_history(self, session_id: str, chat_history: Union[List]) -> None: #List[Chat], 
        return self._client.set(session_id, json.dumps(chat_history))
    
    def delete(self, key: str) -> None:
        self._client.delete(key)
    
    def flush_db(self):
        self._client.flushdb()
    
