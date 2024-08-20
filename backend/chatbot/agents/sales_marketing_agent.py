from langchain_openai import ChatOpenAI
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
)  # PromptTemplate,
from langchain_openai import ChatOpenAI
import os


llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0, streaming=True)


def run_upselling_agent():
    return "This agent is not currently available right now. Please, check back later."