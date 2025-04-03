# from langchain_core.
from ..product_agent import run_product_agent
from ..upselling_agent import run_upselling_agent
from ..payment_verification_agent import run_verification_agent
from ..customer_complaint_agent import run_customer_complaint_agent
from ..logistics_agent import run_logistics_agent
from ..payment_verification_agent import run_verification_agent
import json
from backend.db.cache_utils import get_user_state, modify_user_state, delete_user_state
from backend.db.db_utils import *
from fastapi import BackgroundTasks
from ..agent_models_init import user_chain, str_output_parser

# Agent functions: these are the functions that will be called when a specific agent (based on an identified task) is invoked.

agent_functions = {
    "ProductInfo": run_product_agent,
    "PaymentVerification": run_verification_agent,
    "Logistics": run_logistics_agent,
    "AdsMarketing": run_upselling_agent,
    "CustomerComplaint": run_customer_complaint_agent,
}
   
async def chat(user_request, background_tasks: BackgroundTasks, reset_user_state=True, debug=True):
    # Fetch or initialize user state
    user_state = await get_user_state(user_request.user_id, user_request.vendor_id)
    if debug:
        print("Initial user_state: ", user_state)

    if not user_state:
        business_information = await get_business_info(user_request.vendor_id)
        
        user_state = {
            "chat_history": [],
            "business_information": business_information
        }
        
    else:
        business_information = user_state["business_information"]
        
    if debug:
            print("Business information: ", business_information)

    # Prepare input for the chain
    chain_input = {
        "user_message": user_request.message,
        "business_name": business_information["business_name"],
        "description": business_information["business_description"],
        "facebook_page": business_information["facebook_page"],
        "twitter_page": business_information["twitter_page"],
        "website": business_information["website"],
        "tiktok": business_information["tiktok"],
        "ig_page": business_information["ig_page"],
        "chat_history": user_state.get("chat_history", [])
    }

    # Get response from the chain
    response = user_chain.invoke(chain_input)

    # Handle agent calls if response content is empty
    if response.content == "":
        tool_called = response.additional_kwargs.get("tool_calls")[0].get("function")
        function_name = tool_called["name"]
        try:
            args = json.loads(tool_called["arguments"])
            args.update({
                "user_state": user_state,
                "background_tasks": background_tasks,
                "customer_message": user_request.message,
                "business_id": user_request.vendor_id,
                "customer_id": user_request.user_id,
                "logistic_id": business_information["logistic_id"],
                "vendor_phone_number": business_information["vendor_phone_number"]
            })
        except Exception as e:
            print("Error: ", e)
            raise

        if debug:
            print("Current conversation stage: ", args["conversation_stage"])
            print("Arguments:", args)

        # Call agent and fetch response
        agent_function = agent_functions[function_name]
        response, user_state = await agent_function(**args)
    else:
        response = str_output_parser.invoke(response)

    # Update the chat history
    user_state["chat_history"].extend([
        {"role": "user", "name": "customer", "content": user_request.message},
        {"role": "assistant", "name": "vendor", "content": response}
    ])

    # Update or reset user state
    if reset_user_state:
        await delete_user_state(user_request.user_id, user_request.vendor_id)
    else:
        await modify_user_state(user_request.user_id, user_request.vendor_id, user_state)

    return response