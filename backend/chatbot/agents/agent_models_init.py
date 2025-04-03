from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain.output_parsers.openai_functions import JsonOutputFunctionsParser
from langchain_openai import ChatOpenAI
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate
)  

#prompts
from ..prompts.prompt import business_chat_prompt
from ..prompts.prompt import base_prompt
from ..prompts.central_agent_prompt import *

#Agent Schemas
from .schema.user_function_args_schema import arg_schema as user_arg_schema
from .schema.business_function_args_schema import arg_schema
from .utils.central_agent import Response
from upselling_agent import run_upselling_agent
# others
from typing import List, Optional
import os


model_name = os.getenv("MODEL_NAME")
api_key = os.getenv("API_KEY")

# Initialize output parsers
str_output_parser = StrOutputParser()
function_schema_parser = JsonOutputFunctionsParser()


def __initialize__model(MODEL_NAME=model_name, API_KEY=api_key, temperature=0, streaming=False, tools: Optional[List] =[],
                        use_structured_output: Optional[Response]=None):
    """Initialize the model with the given parameters."""
    if 'gpt' in MODEL_NAME:
        model = ChatOpenAI(model=MODEL_NAME, temperature=temperature, streaming=streaming).bind(tools=[convert_to_openai_tool(func) for func in tools])
        model = model.with_structured_output(Response) if use_structured_output is not None else model
    else:
        raise ValueError("Unsupported model type. Only 'gpt' models are supported.")
    
    return model


# Business interface chain
prompt = PromptTemplate.from_template(business_chat_prompt)
business_chain = prompt | __initialize__model(tools=arg_schema)

## User interface chain
prompt = PromptTemplate.from_template(base_prompt)
user_chain = prompt | __initialize__model(tools=user_arg_schema)

##Central agent chains
system_message = SystemMessagePromptTemplate.from_template(logistic_system_prompt)
rule_system_message = SystemMessagePromptTemplate.from_template(rule_system_prompt)
human_message = HumanMessagePromptTemplate.from_template(human_prompt)

## Define prompt for logistics
logistic_prompt = ChatPromptTemplate.from_messages(
    [
        system_message,
        human_message,
        rule_system_message,
    ]
)

# Define prompt for customer feedback 
system_message = SystemMessagePromptTemplate.from_template(customer_feedback_system_prompt)
rule_system_message = SystemMessagePromptTemplate.from_template(rule_system_prompt)
human_message = HumanMessagePromptTemplate.from_template(human_prompt)

customer_feedback_system_prompt = ChatPromptTemplate.from_messages(
    [
        system_message,
        human_message,
        rule_system_message,
    ]
)

# Define prompt for available products
system_message = SystemMessagePromptTemplate.from_template(unavailable_product_system_prompt)
rule_system_message = SystemMessagePromptTemplate.from_template(rule_system_prompt)
human_message = HumanMessagePromptTemplate.from_template(human_prompt)

unavailable_product_prompt = ChatPromptTemplate.from_messages(
    [
        system_message,
        human_message,
        rule_system_message,
    ]
)

# Define prompt for payment verification
system_message = SystemMessagePromptTemplate.from_template(payment_verification_system_prompt)
rule_system_message = SystemMessagePromptTemplate.from_template(rule_system_prompt)
human_message = HumanMessagePromptTemplate.from_template(human_prompt)

payment_verification_prompt = ChatPromptTemplate.from_messages(
    [
        system_message,
        human_message,
        rule_system_message,
    ]
)


## Central agent chains with tools
llm = __initialize__model(tools=[run_upselling_agent],
                          use_structured_output=Response)
# Map each chain to the appropriate task for central agent
central_agent_chains = {
    "Logistic planning": logistic_prompt | llm, 
    "Payment verification": payment_verification_prompt | llm,
    "Customer Feedback": customer_feedback_system_prompt | llm, 
    "Product Unavailable": unavailable_product_prompt | llm
}


## Agent responsible for fetching performance metrics and deriving insights to businesses.
business_agent = ...