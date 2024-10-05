from typing import List, Optional, Union

from redis import Redis
from dotenv import load_dotenv
import os
import json

load_dotenv()
DEBUG = os.getenv("DEBUG")


class Cache:
    def __init__(self, host: str, port: int, password: str, url: Optional[str] = None):
        if url:
            self._client = Redis.from_url(url, decode_responses=True)
        else:
            self._client = Redis(
                host=host,
                port=port,
                password=password,
                decode_responses=True
            )

    def set(self, key: str, val: dict) -> None: 
        self._client.set(key, json.dumps(val))

    def get(self, key: str) -> Optional[dict]:
        value = self._client.get(key)
        if value:
            return json.loads(value)
        return None

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
    
    def flush_db(self) -> None:
        self._client.flushdb()
    
