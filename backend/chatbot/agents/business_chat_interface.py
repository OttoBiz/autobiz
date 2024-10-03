from backend.db.db_utils import *
from .central_agent_utils import create_structured_input
from fastapi import BackgroundTasks
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from ..prompts.prompt import business_chat_prompt
from langchain_core.utils.function_calling import convert_to_openai_tool
from backend.db.cache_utils import get_user_state, modify_user_state, delete_user_state
from backend.db.db_utils import *
from fastapi import BackgroundTasks
from .business_function_args_schema import arg_schema
import json

prompt = PromptTemplate.from_template(business_chat_prompt)
llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0, streaming=True).bind(
    tools=[convert_to_openai_tool(func) for func in arg_schema]
)

chain = prompt | llm  
str_output_parser = StrOutputParser()

agent_functions = {
    
}
    
async def business_chat(business_request, background_tasks: BackgroundTasks, debug=False):
    from .central_agent import run_central_agent

    # We use the vendor_id as key to fetch the business state.
    user_state  = await get_user_state(business_request.vendor_id, business_request.vendor_id)
    if debug:
        print("Initial user_state: ", user_state)
        
    # fetch chat history
    if not user_state:
        chat_history = []
        user_state = {"chat_history": chat_history}
    else:
        chat_history  = user_state.get("chat_history",[])
        
    response = chain.invoke({"business_message": business_request.message,
                             "chat_history": chat_history})
    
    # If a tool is called: for either central agent or other tools
    if response.content == "":
        tool_called = response.additional_kwargs.get("tool_calls")[0].get("function")
        function_name = tool_called["name"]
        try:
            args = json.loads(tool_called["arguments"])
            args.update({"user_state": user_state,
                         })
        except:
            pass
        
        if not bool(args["for_central_agent"]): # if the business (vendor/logistic) message is not related to the central agent (isn't a response to a central agent's previous message)
            # Call agent and fetch response.
            # response, user_state = await agent_functions[function_name](**args)
            
            # # Update the chat history
            # user_state["chat_history"].extend([{"role": "user" , "name": "business", "content": business_request.message},
            #                         {"role": "assistant", "name": "ai", "content": response}])
            # return response
            return "Hello, Testing..."
        
        else: # Else parse message for central agent.
            agent_input = await create_structured_input(sender=business_request.sender, recipient="agent", message=business_request.message, 
                                                    product_name=business_request.product_name, price= business_request.product_price, 
                                                    customer_id= business_request.user_id, business_id = business_request.vendor_id,
                                                    logistic_id = business_request.logistic_id, message_type=business_request.message_type,
                                        )
            
            # Update the chat history
            user_state["chat_history"].extend([{"role": "user" , "name": "business", "content": business_request.message}])
            # run central agent in the background. 
            background_tasks.add_task(run_central_agent, agent_input, user_state)      
        return 
    
    else: # if no tool is called reply business directly
        response = str_output_parser.invoke(response)
        
        # Update the chat history
        user_state["chat_history"].extend([{"role": "user" , "name": "business", "content": business_request.message},
                            {"role": "assistant", "name": "ai", "content": response}])
        return response