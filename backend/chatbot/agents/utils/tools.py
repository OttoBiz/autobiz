import os
from langchain_core.tools import tool
from ..schema.user_function_args_schema import *
from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper
from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from dotenv import load_dotenv
import base64
from typing import List, Tuple, Union, Dict
import tiktoken
from datetime import datetime, timedelta
import re
import json

load_dotenv()

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0, streaming=True)

search = TavilySearchAPIWrapper()
tavily_tool = TavilySearchResults(api_wrapper=search)


@tool
def get_info_from_internet(text: str) -> str:
    "Useful for when you need information from the internet."
    return tavily_tool.invoke(text)

# Open the image file and encode it as a base64 string
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def string_to_datetime(timestamp_str, format='%Y-%m-%d %H:%M:%S'):
    """
    Converts a string timestamp to a datetime object.

    Parameters:
        timestamp_str (str): The string representation of the timestamp.
        format (str): The format of the timestamp string. Default is '%Y-%m-%d %H:%M:%S'.

    Returns:
        datetime: The datetime object.
    """
    return datetime.strptime(timestamp_str, format)


def datetime_to_timestamp(datetime_obj):
    """
    Converts a datetime object to a timestamp.

    Parameters:
        datetime_obj (datetime): The datetime object.

    Returns:
        float: The timestamp.
    """
    return datetime.timestamp(datetime_obj)


def within_24_hours(datetime_obj1: Union[List[datetime],datetime], datetime_obj2):
    """
    Checks if two datetime objects are within 24 hours of each other.

    Parameters:
        datetime_obj1 (datetime): The first datetime object.
        datetime_obj2 (datetime): The second datetime object.

    Returns:
        bool: True if within 24 hours, False otherwise.
    """
    if type(datetime_obj1) == list:
        datetime_obj1 = sort_datetime_objects(datetime_obj1)[0]
        
    time_difference = abs(datetime_obj1 - datetime_obj2)
    return time_difference <= timedelta(hours=24)

def sort_datetime_objects(datetime_list: List):
    """
    Sorts a list of datetime objects from the most recent to the oldest.

    Parameters:
        datetime_list (list): List of datetime objects.

    Returns:
        list: Sorted list of datetime objects.
    """
    return sorted(datetime_list, key=lambda x: x, reverse=True)


def get_current_date_time():
    """
    Gets the current time.

    Returns:
        datetime: The current datetime object.
    """
    return datetime.now()


def analyze_datetime(datetime_obj):
    """
    Analyzes a datetime object and returns the time of the day and formatted date.

    Parameters:
        datetime_obj (datetime): The datetime object.

    Returns:
        tuple: A tuple containing the time of the day and formatted date.
    """
    # Get the time of the day
    hour = datetime_obj.hour
    if 5 <= hour < 12:
        time_of_day = "Morning"
    elif 12 <= hour < 18:
        time_of_day = "Afternoon"
    else:
        time_of_day = "Night"

    # Format the date
    formatted_date = datetime_obj.strftime("%dth %B %Y")

    return time_of_day, formatted_date


def run_agent(agent, input_variables):
    """
    Runs the specified agent by invoking it with the given input variables.

    Parameters:
    - agent: The agent to run.
    - input_variables: The input variables to provide to the agent.

    Returns:
    The result of invoking the agent.
    """
    return agent.invoke(input_variables)


def summarize_conversations(agent, chat_history, new_session= False,  batch_size= 2048, context_window=-1, ignore_n_messages=6 ):
    """
    Summarizes conversations using the specified agent and chat history.

    Parameters:
    - agent: The agent responsible for summarizing.
    - chat_history: The history of the chat to be summarized.
    - context_window: The size of the context window, -1 indicates using the entire chat history.
    - new_session: Whether the history passed is from a new session or old one.
    - batch_size: size to split data into for batch summarization.
    - ignore_n_messages: Number of most recent messages to not summarize in the chat_history.

    Returns:
    The summarized result based on the provided context.
    """
    if not new_session:
        chat_history = [ [chat_history[batch_ind: batch_ind + batch_size]]  for batch_ind in range(0, len(chat_history), batch_size)]
        
        summary = agent.batch([{"chat_history": history_fragment} for history_fragment in chat_history])
        
        return summary 
    
    # For alpha text purpose: to be removed afterwards.
    elif len(chat_history) > batch_size * 2:
        chat_history = [ [chat_history[batch_ind: batch_ind + batch_size]]  for batch_ind in range(0, len(chat_history[:-ignore_n_messages]), batch_size)]
        
        summary = agent.batch([{"chat_history": history_fragment} for history_fragment in chat_history])
        
        return summary 
    else:
        if context_window == -1:
            summary = [agent.invoke({"chat_history": chat_history[:-ignore_n_messages]})]
            summary.extend(chat_history[-ignore_n_messages:])
            return summary
        else:
            summary = [agent.invoke({"chat_history": chat_history[-(context_window * 2 + ignore_n_messages) : - ignore_n_messages]})]
            summary.extend(chat_history[-ignore_n_messages:])
            return summary
    
    
def format_communication(chat_history: List[Tuple]) -> List[dict]:
    """
    Standardize the chat history by formatting messages with user and assistant roles.

    Parameters:
    - chat_history (List[Tuple]): List of messages in the chat history.

    Returns:
    List[dict]: Standardized chat history with formatted messages.
    """
    history = []
    
    for (sender, msg) in chat_history:
        history.append({"name": f"{sender}", "role": "user", "content": msg})
        
    #print(history)
    return history


def history_to_db_format(chat_history, user_id, chatbot_id, session_id):
    if len(chat_history) == 0:
        return []
    
    history = []
    for message in chat_history:
        if message["role"] == "user":
            history.append({"from_user_id": user_id, "to_user_id": chatbot_id, "session_id": session_id, "content": message["content"]})
        else:
            history.append({"from_user_id": chatbot_id, "to_user_id": user_id, "session_id": session_id, "content": message["content"]})
               
    return history
            

def num_tokens_from_string(string: str, encoding_name: str = "gpt-3.5-turbo") -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.encoding_for_model(encoding_name)
    num_tokens = len(encoding.encode(string))
    return num_tokens


def num_tokens_from_messages(messages, model="gpt-3.5-turbo"):
    """Return the number of tokens used by a list of messages."""
    if not messages or len(messages) == 0:
        return 0
    if type(messages[0]) == str:
        messages = format_communication(messages) # change to standardize chat history later.
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        print("Warning: model not found. Using cl100k_base encoding.")
        encoding = tiktoken.get_encoding("cl100k_base")
    if model in {
        "gpt-3.5-turbo-0613",
        "gpt-3.5-turbo-16k-0613",
        "gpt-4-0314",
        "gpt-4-32k-0314",
        "gpt-4-0613",
        "gpt-4-32k-0613",
        }:
        tokens_per_message = 3
        tokens_per_name = 1
    elif model == "gpt-3.5-turbo-0301":
        tokens_per_message = 4  # every message follows <|start|>{role/name}\n{content}<|end|>\n
        tokens_per_name = -1  # if there's a name, the role is omitted
    elif "gpt-3.5-turbo" in model:
        return num_tokens_from_messages(messages, model="gpt-3.5-turbo-0613")
    elif "gpt-4" in model:
        print("Warning: gpt-4 may update over time. Returning num tokens assuming gpt-4-0613.")
        return num_tokens_from_messages(messages, model="gpt-4-0613")
    else:
        raise NotImplementedError(
            f"""num_tokens_from_messages() is not implemented for model {model}. See https://github.com/openai/openai-python/blob/main/chatml.md for information on how messages are converted to tokens."""
        )
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            num_tokens += len(encoding.encode(value))
            if key == "name":
                num_tokens += tokens_per_name
    num_tokens += 3  # every reply is primed with <|start|>assistant<|message|>
    return num_tokens


def stringify(obj):
    """
    Converts a nested dictionary to a string.

    Parameters:
    - obj: The object to stringify.

    Returns:
    The string representation of the object.
    """
    if isinstance(obj, dict):
        result = ""
        for key, value in obj.items():
            if isinstance(value, dict):
                for k, v in value.items():
                    result += (k + ":" + v)
            result += (key + ":" + value)
    else:
        result = obj

    return result


def convert_tuple_history_to_list(chat_history: List[Tuple]) -> str:
    """
    Converts a chat history from a list of tuples to a formatted string.

    Parameters:
    - chat_history: The chat history to convert.

    Returns:
    The formatted string representation of the chat history.
    """
    buffer = ""
    for dialogue_turn in chat_history:
        human = "Human: " + dialogue_turn[0]
        ai = "Tunu: " + dialogue_turn[1]
        buffer += "\n" + "\n".join([human, ai])
    return buffer

def convert_history_to_list(chat_history: str) -> List[str]:
    """
    Convert chat history string to a list of messages.

    Args:
        chat_history (str): The chat history string.

    Returns:
        List[str]: A list of messages.
    """
    return chat_history.split("\n")


def convert_history_to_string(chat_history: List[str]) -> str:
    """
    Convert a list of messages to a chat history string.

    Args:
        chat_history (List[str]): The list of messages.

    Returns:
        str: The chat history string.
    """
    return "\n".join(chat_history)


def get_chat_history_window(chat_history: Union[str, List[str]], context_window: int = 30) -> List[str]:
    """
    Get a window of chat history messages.

    Args:
        chat_history (Union[str, List[str]]): The chat history as a string or list of messages.
        context_window (int): The size of the context window.

    Returns:
        List[str]: A window of chat history messages.
    """
    if isinstance(chat_history, str):
        chat_history = chat_history.split("\n")
    
    return chat_history[-(context_window * 2):]


def cal_avg_messages(previous_sessions: Dict, n_sessions: int) -> int:
    """
    Calculate the average number of messages per session.

    Args:
        previous_sessions (Dict): The list of messages.
        n_sessions (int): The number of sessions.

    Returns:
        int: The average number of messages per session.
    """
    if not previous_sessions:
        return 0
    
    chat_history = previous_sessions.get("chat_history", [])
    return round((len(flatten_list(chat_history)) / 2) / n_sessions)


def map_to_score(value: str, score_mapping: dict) -> int:
    """
    Map a value to a score based on a predefined mapping.

    Args:
        value (str): The value to be mapped.
        score_mapping (dict): The mapping of values to scores.

    Returns:
        int: The mapped score.
    """
    if value is not None:
        value_lower = value.lower()
        for key, score in score_mapping.items():
            if re.search(fr'\b(?:{key})\b', value_lower, flags=re.IGNORECASE):
                return score
    return 0


async def update_dict(old_dict, new_dict):
    """
    Update a dictionary recursively.

    Parameters:
    - old_dict (dict): Original dictionary.
    - new_dict (dict): Dictionary to update.

    Returns:
    dict: Updated dictionary.
    """
    if type(old_dict) == str:
        old_dict = json.loads(old_dict)
    if type(new_dict) == str:
        new_dict = json.loads(new_dict)
    # print()
    print("In update_dict: ", new_dict)
    for key, value in old_dict.items():
        if key not in new_dict.keys():
            new_dict[key] = value
        elif type(value) == dict:
            print("old value: ", value)
            print("new value: ", new_dict[key])
            new_dict[key] = await update_dict(value, new_dict[key])
    return new_dict


def flatten_list(lst):
    """
    Flatten a list of lists into a single list.

    Args:
    - lst (list): The list of lists to be flattened.

    Returns:
    - list: The flattened list.

    Example:
    >>> flatten_list([[1, 2, 3], [4, 5], [6]])
    [1, 2, 3, 4, 5, 6]
    """
    
    #if list is empty
    if len(lst) == 0:
        return lst
    # Check if the list contains of lists.
    elif isinstance(lst[0], list):
        # Use list comprehension to flatten the list
        flattened_list = [item for sublist in lst for item in sublist] 
    else:
        return lst

    return flattened_list


if __name__ == '__main__':
    pass
  
