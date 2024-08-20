from langchain_openai import ChatOpenAI
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
)  # PromptTemplate,
from langchain_openai import ChatOpenAI
from .product_agent import product_agent
from typing import Annotated, List, Tuple, TypedDict, Union
from langchain_core.pydantic_v1 import BaseModel, Field, Optional
from ..prompts.central_agent_prompt import *
from backend.db.cache_utils import get_user_state, modify_user_state
from tools import format_communication


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
                                processes: {}
                            },
                            product2: {
                                retrieved_result (from database): List[str] list of products
                                db_queried: bool
                                available_products : List[str] of products
                                processes: {}
                            }
                        },
                        business_information:{
                            business_name: 
                            acc_name : 
                            acc_number:
                        },
                        chat_history:{}
}

A central agent's process will typically be as follows:
processes = {
    "Logistic_planning": {
        communication_history:[],
        logistic_id: "",
        customer_address: ""
        },
    "Customer_feedback": {
        communication_history: [],
        
    },
    "Unavailable_product": {
        communication_history: [],
    }
        
}

"""

class Input(BaseModel):
    sender_type: List[str] = ["Agent", "Customer", "Vendor", "Logistics"]
    sender: str
    recipient: str
    response: str
    business_id: Optional[str] = None
    customer_id: Optional[str]
    message: str
    product_name: str
    price: str
    message_type: List[str] = ["Logistic planning", "Customer Feedback", "Product Unavailable"]
    
    def to_dict(self):
        return self.dict()
class Product(BaseModel):
    product_name: str 
    price: str
    chat_history: Optional[List[str]] = None
    task_type: str
    system_prompt: Optional[str]
    logistic_id: Optional[str]
    logistic_details: Optional[str]
    
    def to_dict(self):
        return self.dict()
    
class Response(BaseModel):
    """Response."""
    recipient: List[str] = ["Agent", "Customer", "Vendor", "Logistics"]
    sender: str
    customer_id: str
    business_id: str
    vendor_id: Optional[str] = ""
    message: str
    product: str
    finished: bool
    
    def to_dict(self):
        return self.dict()



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


llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0, streaming=True).with_structured_output(Response)

llm_chains = {
    "Logistic planning": logistic_prompt | llm, 
    "Customer Feedback": customer_feedback_system_prompt | llm, 
    "Product Unavailable": unavailable_product_prompt | llm
}

async def run_db_agent():
    pass

# Function to create structured Input
async def create_structured_input(sender: str, recipient: str, response: str, message: str, product_name: str, price: str, customer_id: Optional[str] = None, business_id: Optional[str] = None):
    structured_input = Input(
        sender=sender,
        recipient=recipient,
        response=response,
        message=message,
        product_name=product_name,
        price=price,
        customer_id=customer_id,
        business_id=business_id
    )
    return structured_input

# Function to create structured Response
async def create_structured_response(sender: str, recipient: List[str], customer_id: str, business_id: str, message: str, product: str, finished: bool, vendor_id: Optional[str] = None):
    structured_response = Response(
        sender=sender,
        recipient=recipient,
        customer_id=customer_id,
        business_id=business_id,
        message=message,
        product=product,
        finished=finished,
        vendor_id=vendor_id if vendor_id else ""
    )
    return structured_response

async def run_central_agent(event_message: Input):
    user_id, vendor_id = event_message.customer_id, event_message.business_id
    user_state = get_user_state(user_id, vendor_id)
    product = user_state.get('products', {}).get(event_message.product_name, {})
    processes = product.get("processes", None)
    
    if not processes:
        processes = {"communication_history": [(event_message.sender_type, event_message.message)]}

    else:
        processes["communication_history"].append((event_message.sender_type, event_message.message))
    
    central_chain = llm_chains[event_message.message_type]
    
    #TODO: The chain inputs differ based on the llm_chain called. Handle this.
    chain_inputs = {
        "product_name": event_message.product_name,
        "customer_id": event_message.customer_id,
        "business_id": event_message.business_id,
        "communication_history": format_communication(processes["communication_history"])
    }
   
    response = central_chain.invoke(chain_inputs)
    # Update product and processes to the user state
    processes["communication_history"].append((response.sender, response.message))
    product["processes"] = processes
    user_state['products'][event_message.product_name] = product
    
    modify_user_state(event_message.customer_id, event_message.business_id, user_state)
    
    # This is where we will have the function calls.
    if response.recipient == "Customer":
        return response
    elif response.recipient == "Logistics":
        pass
    elif response.recipient == "Vendor":
        vendor_message = input(response.message + "\n")
          
    else: # If its agent
        return "Not yet implemented."