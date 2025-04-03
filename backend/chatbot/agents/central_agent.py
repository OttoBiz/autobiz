from backend.db.cache_utils import get_user_state, modify_user_state
# from .tools import format_communication
from .utils.central_agent import *
from backend.whatsapp.utils import whatsapp
from .agent_models_init import central_agent_chains as llm_chains
from typing import Dict, Union
from backend.db.cache_utils import get_contact

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
                processed_orders: {
                    product_name1: ...,
                    product_name2: ...
                },
                business_information:{
                    business_name: 
                    acc_name : 
                    acc_number:
                },
                chat_history:...
}

A central agent's process will typically be as follows (only one of the following as these events are mutually exclusive):
processed_orders =  { product1: {
            communication_history:[],
            logistic_id: "",
            customer_address: "",
            "task_type": ['Logistic_planning', 'Customer_feedback', 'Unavailable_product', 'Payment_verification']
        }

"""


# Define run_central_agent function
async def run_central_agent(event_message: Union[Input, Dict], debug=False):
    if debug:
        print(event_message)
    
    customer_id = event_message["customer_id"]
    business_id = event_message["business_id"]
        
    user_state = get_user_state(customer_id, business_id)
        
    if debug:
        print("user_state inside central agent: ", user_state["chat_history"])
    
    
    # Fetch the necessary items once to prevent multiple look ups.
    product_name = event_message["product_name"]
    task_type = event_message["task_type"]
    price = event_message["price"]
    message = event_message["message"]
    sender = event_message["sender"]
    logistic_id = event_message["logistic_id"]
    
    # Fetch all sales_processes that exist between this customer and vendor business
    #If there are no sales_processes, create a new order process for the appropriate sales_process_stage (i.e logistic planning)
    # between vendor business and customer.
    processed_orders = user_state.get("processed_orders", {product_name: await create_order_process(task_type, 
                    price, [{"role": "user", "name": event_message["sender"], "content": message}], logistic_id)})
    
    order_being_processed = processed_orders.get(product_name, await create_order_process(task_type, price, 
                            [{"role": "user", "name": event_message["sender"], "content": message}], logistic_id))

    order_being_processed["communication_history"].append({"role": "user", "name": sender, "content": message})
    
    central_chain = llm_chains[order_being_processed["task_type"]]
    
    if debug:
        print("Communication history: ", order_being_processed["communication_history"])
        
    # get and process chain inputs for the payment verification chain
    chain_inputs = await get_chain_input_for_order_process(product_name, event_message["customer_id"],
                                            event_message["business_id"], event_message["logistic_id"], order_being_processed["communication_history"],
                                            price=order_being_processed["price"], bank_details = event_message["customer_bank_details"])

   
    # Fetch agent response
    response = await central_chain.ainvoke(chain_inputs)
    
    # get sender and recipient
    sender = response.sender
    recipient = response.recipient

    
    # Add agents response to the communication history
    order_being_processed["communication_history"].append({"role": "user" if sender.lower() != 'agent' else 'assistant', 
                                                           "name":sender, "content": response.message})

    if debug:
        print("Response:", response.message)
        print("Sender: ", sender)
        print("Recipient: ", recipient)
    
    if user_state is not None : #Add agent's response to chat history.
        user_state['chat_history'].append({"role": "assistant", "name": sender, "content": response.message})
    
    if debug:
        print("Communication_history: ", order_being_processed["communication_history"])
        
    # If agent has achieved its objective
    if response.finished: 
        # delete processes for that product
        del processed_orders[product_name]
    else:
        # Update processes for that product in the user state process
        processed_orders[product_name] = order_being_processed
                
    user_state['processed_orders'] = processed_orders

    if event_message['sender'] == "business":
        await modify_user_state(business_id, business_id, user_state)
    else:
        await modify_user_state(customer_id, business_id, user_state)
        
    
    if debug:
        print("user_state inside central agent: ", user_state["chat_history"])
        print("Model Response: ", response)
    
    #TODO: Handle the case where the recipient is an Agent
    # Get the user_name / phone number for the sender
    sender_number = get_contact(sender, event_message)
    recipient_number = get_contact(recipient, event_message)
    
    #TODO: handle order id generation
    if recipient.lower() == "customer":
        response_message = response.message
    else:
        response_message = f"*Customer id: *{customer_id}\n*Business id: *{business_id}\n*Logistic id: *{logistic_id}\n\n{response.message}"
    
    # send message to recipient.
    return whatsapp.send_message(sender_number, recipient_number, response_message)
    