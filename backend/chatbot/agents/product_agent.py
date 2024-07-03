# from langchain_core.
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
)  # PromptTemplate,
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent
from ..prompts.produt_agent_prompt import *
from .tools import *


llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0, streaming=True)


tools = [
    get_info_from_internet,
]

# print(tavily_tool.invoke("who is micheal jackson?"))

system_message = SystemMessagePromptTemplate.from_template(system_prompt)
rule_system_message = SystemMessagePromptTemplate.from_template(rule_system_prompt)
human_message = HumanMessagePromptTemplate.from_template(human_prompt)

prompt = ChatPromptTemplate.from_messages(
    [
        system_message,
        human_message,
        rule_system_message,
        MessagesPlaceholder("agent_scratchpad"),
    ]
)

# Choose the LLM that will drive the agent
llm = ChatOpenAI(model="gpt-3.5-turbo-1106", temperature=0)  # , streaming=True)

# Construct the OpenAI Tools agent
agent = create_openai_tools_agent(llm, tools, prompt)

# Create an agent executor by passing in the agent and tools
product_agent = AgentExecutor(agent=agent, tools=tools, verbose=True)


def run_product_agent(
    customer_message,
    product_name,
    product_category,
    intent,
    tone,
    instruction=None,
    miscellaneous=None,
    use_internet=False,
    **kwargs
):

    return product_agent.invoke(
        {
            "customer_message": customer_message,
            "product_name": product_name,
            "product_category": product_category,
            "intent": intent,
            "tone": tone,
            "use_internet": str(use_internet),
            "miscellaneous": miscellaneous,
            "instruction": instruction,
        }
    )
