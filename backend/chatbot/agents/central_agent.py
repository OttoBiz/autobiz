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

A central agent's process will typically be as follows (only one of the following as these events are mutually exclusive):
process = 
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
    user_state = get_user_state(user_id, vendor_id)
    
    if "products" in user_state.keys():
        product = user_state.get('products').get(event_message.product_name, {})
    else:
        user_state['products'] = {}
        product = {} 
        
    process = product.get("process", None)
    
    if not process:
        process = create_structured_process(event_message.product_name, event_message.message_type, 
                    event_message.price, [(event_message.sender, event_message.message)]) #{"communication_history": [(event_message.sender_type, event_message.message)]}
    else:
        process.communication_history.append((event_message.sender, event_message.message))
    
    central_chain = llm_chains[event_message.message_type]
    
    #TODO: The chain inputs differ based on the llm_chain called. Handle this.
    chain_inputs = {
        "product_name": event_message.product_name,
        "customer_id": event_message.customer_id,
        "business_id": event_message.business_id,
        "communication_history": format_communication(process.communication_history)
    }
   
    response = central_chain.invoke(chain_inputs)
    # Update product and processes to the user state
    process.communication_history.append((response.sender, response.message))
    
    # If agent has achieved its objective
    if response.finished: 
        # delete processes for that product
        product['process'] = None
    else:
        product["process"] = process
        
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
    

# event_message = create_structured_input(
#     "customer", "vendor", 'please, how soon can I get the iphone', 'Iphone 12', '$1550', '23aogoag', '2efecao','45oavnso'
# )

# response  = run_central_agent(event_message)    