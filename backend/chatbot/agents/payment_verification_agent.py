from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate, MessagesPlaceholder # PromptTemplate, 
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent
from .tools import *

import os

llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0, streaming=True)

