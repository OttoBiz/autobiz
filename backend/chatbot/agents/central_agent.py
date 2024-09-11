from langchain_openai import ChatOpenAI
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate
)  
from langchain_openai import ChatOpenAI
# from .product_agent import product_agent
from ..prompts.central_agent_prompt import *
from backend.db.cache_utils import get_user_state, modify_user_state
from .tools import format_communication
from .central_agent_utils import *
import json

"""
There are usually 3 types of processes handled by the central agent using 3 different system prompts:
1. Logistic planning and arrangements
2. Customer Feedback
3. Unavailable products

Central agent processes are also stored as 'processes' in the user's state using the following schema:
user_state ==  { 
                products: {
                            product1 :{
                                retrieved_result (from database): List[str] list of products
                                db_queried: bool
                                available_products : List[str] of products
                            },
                            product2: {
                                retrieved_result (from database): List[str] list of products
                                db_queried: bool
                                available_products : List[str] of products
                                
                            }
                        },
                        processes: {
                            
                        },
                        business_information:{
                            business_name: 
                            acc_name : 
                            acc_number:
                        },
                        chat_history:{}
}

A central agent's process will typically be as follows (only one of the following as these events are mutually exclusive):
process = 
    "Logistic_planning": { product1: {
            communication_history:[],
            logistic_id: "",
            customer_address: ""
            },
        }
    "Customer_feedback": {product1: {
            communication_history: [],
            }
        
    },
    "Unavailable_product": { product1: {
        communication_history: [],
        }
        },
    "payment verification": { product1: {
        bank_details : {...}
        communication_history: [],
    }
    }
        

"""

system_message = SystemMessagePromptTemplate.from_template(logistic_system_prompt)
rule_system_message = SystemMessagePromptTemplate.from_template(rule_system_prompt)
human_message = HumanMessagePromptTemplate.from_template(human_prompt)

logistic_prompt = ChatPromptTemplate.from_messages(
    [
        system_message,
        human_message,
        rule_system_message,
    ]
)

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

llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0, streaming=True).with_structured_output(Response)


llm_chains = {
    "Logistic planning": logistic_prompt | llm, 
    "Payment verification": payment_verification_prompt | llm,
    "Customer Feedback": customer_feedback_system_prompt | llm, 
    "Product Unavailable": unavailable_product_prompt | llm
}


llm_chains = {
    "Logistic planning": logistic_prompt | llm, 
    "Payment verification": payment_verification_prompt | llm,
    "Customer Feedback": customer_feedback_system_prompt | llm, 
    "Product Unavailable": unavailable_product_prompt | llm
}


async def run_central_agent(event_message: Input):
    user_id, vendor_id = event_message.customer_id, event_message.business_id
    user_state = await get_user_state(user_id, vendor_id)
    processes = user_state.get("processes", {})
    
    product_name = event_message.product_name
    message_type = event_message.message_type
    price = event_message.price
    message = event_message.message
    # customer_id = event_message.customer_id
    # business_id = event_message.business_id
    # logistic_id = event_message.logistic_id
    
    if not processes:
        process = await create_structured_process(product_name, message_type, 
                    price, [{"role": "user", "name": event_message.sender, "content": message}]) #{"communication_history": [(event_message.sender_type, message)]}
        processes[message_type] = {product_name: process}
    else:
        process = processes.get(message_type, 
                   {product_name: await create_structured_process(product_name, message_type, price, [])})
        
        process = process.get(product_name)
        process.communication_history.append({"role": "user", "name": event_message.sender, "content": message})
    
    central_chain = llm_chains[process.task_type]
    print("central_chain: ", central_chain)
    
    if process.task_type == "Payment verification":
        chain_inputs = await get_chain_input_for_process(product_name, event_message.customer_id,
                                               event_message.business_id, event_message.logistic_id, process.communication_history,
                                               price=process.price)
    else:
         chain_inputs = await get_chain_input_for_process(product_name, event_message.customer_id,
                                               event_message.business_id, event_message.logistic_id, process.communication_history,
                                               )
   
   
    response = central_chain.invoke(chain_inputs)
    # Update product and processes to the user state
    process.communication_history.append({"role": "user", "name": response.sender, "content": response.message})
    
    # If agent has achieved its objective
    if response.finished: 
        # delete processes for that product
        processes[message_type][product_name] = None
    else:
        processes[message_type][product_name] = process
        
    user_state['processes'] = processes
    
    modify_user_state(event_message.customer_id, event_message.business_id, user_state)
    
    print("Response: ", response)
    
    # This is where we will have the function calls.
    if response.recipient == "Customer":
        return response
    elif response.recipient == "Logistics":
        return response
    elif response.recipient == "Vendor":
        return response
        # vendor_message = input(response.message + "\n")    
    else: # If its agent
        return "Not yet implemented."
    
    return
    

# event_message = create_structured_input(
#     "customer", "vendor", 'please, how soon can I get the iphone', 'Iphone 12', '$1550', '23aogoag', '2efecao','45oavnso'
# )

# response  = run_central_agent(event_message)    