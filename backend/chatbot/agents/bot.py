# from langchain_core.
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from ..prompts.prompt import base_prompt
from .function_args_schema import arg_schema
from langchain.output_parsers.openai_functions import JsonOutputFunctionsParser
from langchain_core.utils.function_calling import convert_to_openai_tool
from .product_agent import run_product_agent
from .upselling_agent import run_upselling_agent
from .central_agent import run_central_agent
from .payment_verification_agent import run_verification_agent
from .customer_complaint_agent import run_customer_complaint_agent
from .logistics_agent import run_logistics_agent
from .payment_verification_agent import *
import json
from backend.db.cache_utils import get_user_state, modify_user_state
from backend.db.db_utils import *

prompt = PromptTemplate.from_template(base_prompt)
llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0, streaming=True).bind(
    tools=[convert_to_openai_tool(func) for func in arg_schema]
)

chain = prompt | llm  # | StrOutputParser()
function_schema_parser = JsonOutputFunctionsParser()
str_output_parser = StrOutputParser()


# Agent functions
agent_functions = {
    "ProductInfo": run_product_agent,
    "PaymentVerification": run_verification_agent,
    "Logistics": run_logistics_agent,
    "AdsMarketing": run_upselling_agent,
    "CustomerComplaint": run_customer_complaint_agent,
}


#id,business name,ig page,facebook page,twitter page,email,tiktok,website,phone number,business description,business niche,Bank name,
# Bank account number,Bank account name,type,date created
# chat function that interfaces with chatbot
async def chat(user_request):
    ## If state between user and vendor exists in cache, fetch it:
    user_state  = await get_user_state(user_request.user_id, user_request.vendor_id)
    if user_state is None:
        # else fetch vendor's business info
        business_information = await get_business_info(user_request.vendor_id)
        business_information = business_information
        chat_history = []
        user_state = {"chat_history": chat_history , "business_information": business_information}
    else:
        business_information = user_state.get("business_information")
        chat_history  = user_state.get("chat_history",[])
        
    
    response =  chain.invoke({"user_message" : user_request.message,
                              "business_name": business_information["business_name"],
                              "description": business_information["business_description"],
                              "facebook_page": business_information["facebook_page"],
                              "twitter_page": business_information["twitter_page"],
                              "website": business_information["website"],
                              "tiktok": business_information["tiktok"],
                              "ig_page": business_information["ig_page"],
                              "chat_history": chat_history})
    
    if response.content == "":
        tool_called = response.additional_kwargs.get("tool_calls")[0].get("function")
        function_name = tool_called["name"]
        try:
            args = json.loads(tool_called["arguments"])
            args.update({"user_state": user_state, "chat_history": chat_history, 
                         "customer_message": user_request.message,
                         "business_id": user_request.vendor_id, "customer_id": user_request.user_id})
        except:
            pass
        
        conversation_stage = args["conversation_stage"]
        
        response, user_state = await agent_functions[function_name](**args)
        
    else:
        response = str_output_parser.invoke(response)
        
    user_state["chat_history"].extend([{"role": "user" , "name": "customer", "content": user_request.message},
                            {"role": "assistant", "name": "vendor", "content": response}])
    
    await modify_user_state(user_request.user_id, user_request.vendor_id, user_state)
        
    return response
