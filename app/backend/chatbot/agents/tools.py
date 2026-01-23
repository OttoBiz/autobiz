"""
Utility Tools - Converted to use standard Python (no LangChain dependencies)
Legacy utilities kept for backward compatibility
"""
import os
from dotenv import load_dotenv
import base64
from typing import List, Tuple, Union, Dict
import tiktoken
from datetime import datetime, timedelta
import re
import json

load_dotenv()


def encode_image(image_path: str) -> str:
    """Encode image file as base64 string"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def string_to_datetime(timestamp_str: str, format: str = '%Y-%m-%d %H:%M:%S') -> datetime:
    """Convert string timestamp to datetime object"""
    return datetime.strptime(timestamp_str, format)


def datetime_to_timestamp(datetime_obj: datetime) -> float:
    """Convert datetime object to timestamp"""
    return datetime.timestamp(datetime_obj)


def within_24_hours(datetime_obj1: Union[List[datetime], datetime], datetime_obj2: datetime) -> bool:
    """Check if two datetime objects are within 24 hours of each other"""
    if type(datetime_obj1) == list:
        datetime_obj1 = sort_datetime_objects(datetime_obj1)[0]
    
    time_difference = abs(datetime_obj1 - datetime_obj2)
    return time_difference <= timedelta(hours=24)


def sort_datetime_objects(datetime_list: List[datetime]) -> List[datetime]:
    """Sort list of datetime objects from most recent to oldest"""
    return sorted(datetime_list, key=lambda x: x, reverse=True)


def get_current_date_time() -> datetime:
    """Get current datetime"""
    return datetime.now()


def analyze_datetime(datetime_obj: datetime) -> Tuple[str, str]:
    """Analyze datetime and return time of day and formatted date"""
    hour = datetime_obj.hour
    if 5 <= hour < 12:
        time_of_day = "Morning"
    elif 12 <= hour < 18:
        time_of_day = "Afternoon"
    else:
        time_of_day = "Night"
    
    formatted_date = datetime_obj.strftime("%dth %B %Y")
    return time_of_day, formatted_date


def format_communication(chat_history: List[Tuple]) -> List[dict]:
    """Standardize chat history by formatting messages"""
    history = []
    for (sender, msg) in chat_history:
        history.append({"name": f"{sender}", "role": "user", "content": msg})
    return history


def history_to_db_format(chat_history: List[dict], user_id: str, chatbot_id: str, session_id: str) -> List[dict]:
    """Convert chat history to database format"""
    if len(chat_history) == 0:
        return []
    
    history = []
    for message in chat_history:
        if message["role"] == "user":
            history.append({
                "from_user_id": user_id,
                "to_user_id": chatbot_id,
                "session_id": session_id,
                "content": message["content"]
            })
        else:
            history.append({
                "from_user_id": chatbot_id,
                "to_user_id": user_id,
                "session_id": session_id,
                "content": message["content"]
            })
    return history


def num_tokens_from_string(string: str, encoding_name: str = "gpt-3.5-turbo") -> int:
    """Return number of tokens in a text string"""
    encoding = tiktoken.encoding_for_model(encoding_name)
    num_tokens = len(encoding.encode(string))
    return num_tokens


def num_tokens_from_messages(messages: List[dict], model: str = "gpt-3.5-turbo") -> int:
    """Return number of tokens used by a list of messages"""
    if not messages or len(messages) == 0:
        return 0
    
    if type(messages[0]) == str:
        messages = format_communication(messages)
    
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    
    tokens_per_message = 3
    tokens_per_name = 1
    
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            num_tokens += len(encoding.encode(str(value)))
            if key == "name":
                num_tokens += tokens_per_name
    num_tokens += 3
    return num_tokens


def stringify(obj: Union[dict, str]) -> str:
    """Convert nested dictionary to string"""
    if isinstance(obj, dict):
        result = ""
        for key, value in obj.items():
            if isinstance(value, dict):
                for k, v in value.items():
                    result += (k + ":" + str(v))
            result += (key + ":" + str(value))
        return result
    else:
        return str(obj)


def convert_tuple_history_to_list(chat_history: List[Tuple]) -> str:
    """Convert chat history from list of tuples to formatted string"""
    buffer = ""
    for dialogue_turn in chat_history:
        human = "Human: " + dialogue_turn[0]
        ai = "AI: " + dialogue_turn[1]
        buffer += "\n" + "\n".join([human, ai])
    return buffer


def convert_history_to_list(chat_history: str) -> List[str]:
    """Convert chat history string to list of messages"""
    return chat_history.split("\n")


def convert_history_to_string(chat_history: List[str]) -> str:
    """Convert list of messages to chat history string"""
    return "\n".join(chat_history)


def get_chat_history_window(chat_history: Union[str, List[str]], context_window: int = 30) -> List[str]:
    """Get a window of chat history messages"""
    if isinstance(chat_history, str):
        chat_history = chat_history.split("\n")
    return chat_history[-(context_window * 2):]


def cal_avg_messages(previous_sessions: Dict, n_sessions: int) -> int:
    """Calculate average number of messages per session"""
    if not previous_sessions:
        return 0
    
    chat_history = previous_sessions.get("chat_history", [])
    return round((len(flatten_list(chat_history)) / 2) / n_sessions) if n_sessions > 0 else 0


def map_to_score(value: str, score_mapping: dict) -> int:
    """Map a value to a score based on predefined mapping"""
    if value is not None:
        value_lower = value.lower()
        for key, score in score_mapping.items():
            if re.search(fr'\b(?:{key})\b', value_lower, flags=re.IGNORECASE):
                return score
    return 0


async def update_dict(old_dict: Union[dict, str], new_dict: Union[dict, str]) -> dict:
    """Update a dictionary recursively"""
    if type(old_dict) == str:
        old_dict = json.loads(old_dict)
    if type(new_dict) == str:
        new_dict = json.loads(new_dict)
    
    for key, value in old_dict.items():
        if key not in new_dict.keys():
            new_dict[key] = value
        elif type(value) == dict:
            new_dict[key] = await update_dict(value, new_dict[key])
    return new_dict


def flatten_list(lst: List) -> List:
    """Flatten a list of lists into a single list"""
    if len(lst) == 0:
        return lst
    
    if isinstance(lst[0], list):
        return [item for sublist in lst for item in sublist]
    else:
        return lst
