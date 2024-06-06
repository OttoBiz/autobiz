
#from langchain_core.
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from ..prompts.prompt import base_prompt
from .function_args_schema import arg_schema
from dotenv import load_dotenv
from langchain.output_parsers.openai_functions import JsonOutputFunctionsParser
from .product_agent import run_product_agent
from .payment_verification_agent import run_question_generator_agent
import json

import os
load_dotenv()


prompt= PromptTemplate.from_template(base_prompt)
llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0, streaming=True).bind(tools=[convert_to_openai_tool(func) for func in arg_schema])

chain = prompt | llm  #| StrOutputParser()
function_schema_parser = JsonOutputFunctionsParser()
str_output_parser = StrOutputParser()


# Agent functions
agent_functions = {"ProductInfo": run_product_agent,
                    "PaymentVerification": ..., 
                    "Logistics": ...,
                    "AdsMarketing": ...,
                    "CustomerComplaint": ...}


# chat function that interfaces with chatbot
async def chat(user_request):
    response =  chain.invoke({"user_message" : user_request.message})
    
    if response.content == "":
        tool_called  = response.additional_kwargs.get("tool_calls")[0].get("function")
        function_name = tool_called["name"]
        args = json.loads(tool_called["arguments"])
        conversation_stage = args["conversation_stage"]
        
        return agent_functions[function_name](**args)
    else:
        return str_output_parser.stream(response)
    

