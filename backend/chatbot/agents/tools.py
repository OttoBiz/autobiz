import os
from langchain_core.tools import tool
from .function_args_schema import *
from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper
from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from dotenv import load_dotenv
import base64

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
