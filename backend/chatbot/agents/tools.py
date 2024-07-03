
from langchain_core.tools import tool
from .function_args_schema import *   
from langchain.utilities.tavily_search import TavilySearchAPIWrapper
from langchain_openai import ChatOpenAI
# from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper

llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0, streaming=True)

search = TavilySearchAPIWrapper()
tavily_tool = TavilySearchResults(api_wrapper=search)

@tool 
def get_info_from_internet(text: str) -> str:
    "Useful for when you need information from the internet."
    return tavily_tool.invoke(text)





