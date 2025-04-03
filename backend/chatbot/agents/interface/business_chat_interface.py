from backend.db.db_utils import *
from ..utils.central_agent import create_structured_input
from fastapi import BackgroundTasks
from ...prompts.prompt import business_chat_prompt
from backend.db.cache_utils import get_user_state, modify_user_state, delete_user_state
from backend.db.db_utils import *
from fastapi import BackgroundTasks
from ..agent_models_init import business_chain as chain, str_output_parser
from ..business_agent import run_business_agent
from ..central_agent import run_central_agent
import json

    
async def business_chat(business_request, background_tasks: BackgroundTasks, debug=False):
    
    # We use the business_id as key to fetch the business state.
    user_state  = await get_user_state(business_request.business_id, business_request.business_id)
    if debug:
        print("Initial user_state: ", user_state)
        
    # fetch chat history
    if not user_state:
        chat_history = []
        user_state = {"chat_history": chat_history}
    else:
        chat_history  = user_state.get("chat_history",[])
        
    response = chain.invoke({"business_message": business_request.message,
                             "business_type": business_request.business_type,
                             "chat_history": chat_history})
    
    # If a tool is called: for either central agent or other tools
    if response.content == "":
        tool_called = response.additional_kwargs.get("tool_calls")[0].get("function")
        try:
            args = json.loads(tool_called["arguments"])
        except json.JSONDecodeError as e:
            print(f"JSON decoding error: {e}")
            args = {}  # Provide a default value or handle accordingly
              
        except Exception as e:
            print(f"Unexpected error: {e}")
            args = {}
        
        if not bool(args["for_central_agent"]): # if the business (vendor/logistic) message is not related to the central agent (isn't a response to a central agent's previous message)  
            
            response = run_business_agent(args['business_message'])
            
            # # Update the chat history
            user_state["chat_history"].extend([{"role": "user" , "name": "business", "content": business_request.message}],
                                              [{"role": "assistant", "name": "ai", "content": response}])
            
            # Modify user_state
            await modify_user_state(business_request.business_id, business_request.business_id, user_state)
            
            return response
            
            # run business agent in the background. 
            
            # background_tasks.add_task(run_business_agent, args['business_message'], user_state) 
            
            # return "Please, hold on while I process your message. I will get back to you shortly."
        
        else: # Else parse message for central agent.
            agent_input = await create_structured_input(sender="business", recipient=args["recipient"], message=args['business_message'], 
                                                    product_name= args['product_name'], price= args['product_price'], 
                                                    customer_id= args['customer_id'], business_id = business_request.business_id,
                                                    logistic_id = args['logistic_id'], message_type=args['task_type'],
                                        )
            # Update the chat history
            user_state["chat_history"].extend([{"role": "user" , "name": "business", "content": business_request.message}])
            
            # Modify user_state
            await modify_user_state(business_request.business_id, business_request.business_id, user_state)
            
            # run central agent in the background. 
            background_tasks.add_task(run_central_agent, agent_input, user_state)      
            
            return "Please, hold on while I process your message. I will get back to you shortly."
    
    else: # if no tool is called (message is about miscellaneous), reply business directly
        response = str_output_parser.invoke(response)
        
        # Update the chat history
        user_state["chat_history"].extend([{"role": "user" , "name": "business", "content": business_request.message},
                            {"role": "assistant", "name": "ai", "content": response}])
        
        # modify state
        await modify_user_state(business_request.business_id, business_request.business_id, user_state)
        
        if debug:
            print("user_state inside business agent: ", user_state["chat_history"])
            
        return response #TODO check businessrequest out