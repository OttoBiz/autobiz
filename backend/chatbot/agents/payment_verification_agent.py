from langchain_openai import ChatOpenAI
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
)  
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.output_parsers import StrOutputParser
from ..prompts.payment_verificatioin_prompt import *
from .tools import *

import os

"""
CRITERIA THAT MUST BE MET FOR A PAYMENT TO BE CONFIRMED AS SUCCESSFUL
1. IF EVIDENCE (PICTURE) IS PROVIDED BY THE CUSTOMER:
    - The agent must have provided bank details to the customer prior in the chat_history or must have had the account number
    maybe from previous chat sessions.
    - The agent must extract customer's bank name, bank account number, amount paid, product purchased, time of payment.
    - There must have been a product being talked about prior in the chat_history (within possibly 24 hrs)
    - Time of payment must be less than current time.
    - amount paid must match the amount of the product.
    - If mono is enabled for vendor, the bank name, account name, account number, amount paid, product purchased must exactly match an
    entry in the monitored account.

2. IF WRITTEN (TEXT) IS PROVIDED BY THE CUSTOMER:
    - The agent must have provided bank details to the customer prior in the chat_history or must have had the account number
    maybe from previous chat sessions.
    - The customer must provide bank name, bank account number, amount paid, product purchased, time of payment.
    - There must have been a product being talked about prior in the chat_history (within possibly 24 hrs)
    - Time of payment must be less than current time.
    - amount paid must match the amount of the product.
    - If mono is enabled for vendor, the bank name, account name, account number, amount paid, product purchased must exactly match an
    entry in the monitored account.
    - Else, these details must be forwarded to the vendor for verbal confirmation. In this case, a timeholder message must be sent to the 
    customer to explain that verification is currently going on.
    
If transaction is sucessful, the vendor must be notified (if mono is enabled) through central agent, conversation will then be handed over to
the logistics and central agents.
"""


llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, streaming=True)

system_message = SystemMessagePromptTemplate.from_template(system_prompt)
rule_system_message = SystemMessagePromptTemplate.from_template(rule_system_prompt)
human_message = HumanMessagePromptTemplate.from_template(human_prompt)
prompt = ChatPromptTemplate.from_messages(
    [
        system_message,
        human_message,
        rule_system_message,
        # MessagesPlaceholder("agent_scratchpad"),
    ]
)

# Create an agent executor by passing in the agent and tools
payment_verification_agent = prompt | llm | StrOutputParser() #AgentExecutor(agent=agent, tools=tools, verbose=True)


async def run_payment_verification_agent():
    return