from typing import List, Literal, Tuple, Union, Optional, Dict    
from pydantic import BaseModel, Field


class Input(BaseModel):
    sender: str  #["Agent", "Customer", "Vendor", "Logistics"]
    recipient: str
    business_id: Optional[str] = ""
    customer_id: Optional[str] = ""
    logistic_id: Optional[str] = ""
    message: str
    product_name: str
    price: Optional[str]
    task_type: Optional[str]  #["Logistic planning", "Customer Feedback", "Product Unavailable", "Payment Verification"]
    customer_address: Optional[str]
    customer_bank_details: Optional[str] = ""
    
    def to_dict(self):
        return self.dict()
    
    
class Process(BaseModel):
    product_name: str 
    price: Optional[str] = ""
    communication_history: Optional[Union[List[str], List[Tuple], List[Dict]]] = None
    task_type: str
    logistic_id: Optional[str] = ""
    logistic_details: Optional[str] = ""
    customer_address: Optional[str] = ""
    
    def to_dict(self):
        return self.dict()
    

class Response(BaseModel):
    """Response."""
    reasoning: str = Field(..., description="Think about what should be done.")
    next_step: str = Field(..., description="Determine your next step and to whom it should be directed.")
    message: str = Field(..., description="your message to the recipient")
    recipient: Literal["Agent", "Customer", "Vendor", "Logistics"]  = Field(..., description="message recipient. One of the following [AI Agent, Customer, Vendor, Logistics]")  # ["Agent", "Customer", "Vendor", "Logistics"]
    sender: Literal["Agent", "Customer", "Vendor", "Logistics"] = Field(..., description="message sender. One of the following [AI Agent, Customer, Vendor, Logistics]")
    logistic_details: Optional[str] = Field(..., description="delivery logistic details")
    finished: bool = Field(..., description="True if your full objective has been achieved else False")
    
    def to_dict(self):
        return self.dict()
    
def get_contact(query, input_):
    if query.lower() == 'customer':
        return input_.get("customer_id")
    elif query.lower() == 'vendor':
        return input_.get("business_id")
    else:
        return input_.get("logistic_id")
    
# Function to create structured Input
async def create_structured_input(sender: str, recipient: str, message: str, product_name: str,
                                  price: str, customer_id: str = "", business_id: Optional[str] = "", 
                                  customer_address: str = "", bank_details: str="", logistic_id: Optional[str] = "",
                                  task_type: str = ""):
    structured_input = {
        "sender":sender,
        "recipient":recipient,
        "message":message,
        "product_name":product_name,
        "price":price,
        "customer_id":customer_id,
        "business_id":business_id,
        "customer_address" : customer_address,
        "customer_bank_details": bank_details,
        "logistic_id":logistic_id,
        "task_type": task_type
    }
    
    return structured_input

# Function to create a structured Process object
async def create_order_process(task_type: str, price: Optional[str] = "",
                                    chat_history: Optional[Union[List[str], List[Tuple]]] = None, 
                                    # system_prompt: Optional[str] = "", 
                                    logistic_id: Optional[str] = "", 
                                    logistic_details: Optional[str] = "",
                                    customer_address: Optional[str]="") -> Process:
   
    order_to_be_processed = {
        "price": price,
        "communication_history":chat_history,
        "task_type":task_type,
        "logistic_id":logistic_id,
        "logistic_details":logistic_details,
        "customer_address" :customer_address
    }
    
    return order_to_be_processed


async def  get_chain_input_for_order_process(product="", customer_id="", business_id="", logistic_id="",
                                       customer_address= "", communication_history="", instruction="", **kwargs):
    chain_input = {
        "product": product,
        "customer_id": customer_id, 
        "business_id": business_id,
        'communication_history': communication_history,
        "instruction": instruction
    }
    
    if logistic_id:
        chain_input["logistic_id"] = f"using logistic company with id:- {logistic_id}"
        
    if customer_address:
        chain_input["customer_address"] = customer_address
    else:
        chain_input["customer_address"] = "Not yet gotten from customer"

       
    if kwargs:
        chain_input.update(**kwargs)
    return chain_input