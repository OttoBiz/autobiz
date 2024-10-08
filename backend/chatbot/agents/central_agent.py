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
# from .tools import format_communication
from .central_agent_utils import *
from backend.whatsapp.utils import whatsapp

import json

"""
There are usually 4 types of processes handled by the central agent using 3 different system prompts:
1. Logistic planning and arrangements
2. Customer Feedback
3. Unavailable products
4. Payment verification


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

llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0, streaming=True).with_structured_output(Response)

# Map each chain to the appropriate task
llm_chains = {
    "Logistic planning": logistic_prompt | llm, 
    "Payment verification": payment_verification_prompt | llm,
    "Customer Feedback": customer_feedback_system_prompt | llm, 
    "Product Unavailable": unavailable_product_prompt | llm
}

# Define run_central_agent function
async def run_central_agent(event_message: Input, user_state =None, vendor_only=False, debug=False):
    print(event_message)
    
    customer_id = event_message["customer_id"]
    business_id = event_message["business_id"]
        
    if user_state is None:
        user_state = get_user_state(customer_id, business_id)
        
    if debug:
        print("user_state inside central agent: ", user_state["chat_history"])
    
    # Fetch all processes that exist between this customer and vendor business
    processes = user_state.get("processes", {})
    
    # Fetch the necessary items once to prevent multiple look ups.
    product_name = event_message["product_name"]
    message_type = event_message["message_type"]
    price = event_message["price"]
    message = event_message["message"]
    sender = event_message["sender"]
   
    # logistic_id = event_message.logistic_id
    
    if not processes:
        #If there are no processes, create a new process between vendor business and customer.
        process = await create_structured_process(product_name, message_type, 
                    price, [{"role": "user", "name": event_message["sender"], "content": message}]) #{"communication_history": [(event_message.sender_type, message)]}
        processes[message_type] = {product_name: process}
    else:
        # Else, get the appropriate process given the product name being handled.
        process = processes.get(message_type, 
                   {product_name: await create_structured_process(product_name, message_type, price, [])})
        
        process = process.get(product_name)
        process["communication_history"].append({"role": "user", "name": event_message["sender"], "content": message})
    
    central_chain = llm_chains[process["task_type"]]
    
    if process["task_type"] == "Payment verification" and sender == 'customer': # if it is a payment verification task
        if debug:
            print("Communication history: ", process["communication_history"])
        # get and process chain inputs for the payment verification chain
        chain_inputs = await get_chain_input_for_process(product_name, event_message["customer_id"],
                                               event_message["business_id"], event_message["logistic_id"], process["communication_history"],
                                               price=process["price"], bank_details = event_message["customer_bank_details"])
    else:
        # Get and process chain inputs for the other chains.
         chain_inputs = await get_chain_input_for_process(product_name, event_message["customer_id"],
                                               event_message["business_id"], event_message["logistic_id"], process["communication_history"],
                                               )
   
    # Fetch agent response
    response = await central_chain.ainvoke(chain_inputs)
    
    # Add agents response to the communication history
    process["communication_history"].append({"role": "user", "name": response.sender, "content": response.message})
    
    
    # get sender and recipient
    sender = response.sender
    recipient = response.recipient
    
    if user_state is not None:
        if recipient == 'Customer' : #Add agent's response to chat history.
            user_state['chat_history'].append({"role": "assistant", "name": sender, "content": response})
        elif recipient == 'Customer':
            user_state['chat_history'].append({"role": "assistant", "name": sender, "content": response})
        elif recipient == 'Customer':
            user_state['chat_history'].append({"role": "assistant", "name": sender, "content": response})
            
    
    if debug:
        print("Communication_history: ", process["communication_history"])
        
    # If agent has achieved its objective
    if response.finished: 
        # delete processes for that product
        del processes[message_type][product_name]
    else:
        # Update processes for that product in the user state process
        processes[message_type][product_name] = process
        
    user_state['processes'] = processes
    
    if vendor_only: # If only vendor/logistic is involved in the chat
        await modify_user_state(business_id, business_id, user_state)
    else:
        await modify_user_state(customer_id, business_id, user_state)
        
    
    if debug:
        print("user_state inside central agent: ", user_state["chat_history"])
        print("Model Response: ", response)
    
    
    # Get the user_name / phone number for the sender
    sender_number = get_contact(sender, event_message)
    recipient_number = get_contact(recipient, event_message)
    
    # send message to recipient.
    whatsapp.send_message(sender_number, recipient_number, response.message)
    
    return
    
    # This is where we will have the function calls.
    # if recipient == "Customer": # if recipient is customer, send the message to customer
    #     return response, user_state
    # elif recipient == "Logistics": # if recipient is logistics, send the message to logistics
    #     return response, user_state
    # elif recipient == "Vendor": # If recipient is vendor, send message to vendor.
    #     return response, user_state
    #     # vendor_message = input(response.message + "\n")    
    # else: # If its agent, send message to agent.
    #     return "Not yet implemented.", user_state