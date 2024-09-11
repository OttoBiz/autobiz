from typing import Annotated, List, Tuple, TypedDict, Union, Optional, Dict
from langchain_core.pydantic_v1 import BaseModel, Field


class Input(BaseModel):
    # sender_type: str  
    sender: str  #["Agent", "Customer", "Vendor", "Logistics"]
    recipient: str
    business_id: Optional[str] = ""
    customer_id: Optional[str] = ""
    logistic_id: Optional[str] = ""
    message: str
    product_name: str
    price: str
    message_type: Optional[str]  #["Logistic planning", "Customer Feedback", "Product Unavailable", "Payment Verification"]
    
    def to_dict(self):
        return self.dict()
    
    
class Process(BaseModel):
    product_name: str 
    price: Optional[str] = ""
    communication_history: Optional[Union[List[str], List[Tuple]]] = None
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
    message: str = Field(..., description="message")
    recipient: str =Field(..., description="message recipient")  # ["Agent", "Customer", "Vendor", "Logistics"]
    sender: str = Field(..., description="message sender")
    customer_id: str =Field(..., description="Customer id")
    business_id: str = Field(..., description="Business id")
    logistic_id: Optional[str] = Field(..., description="Logistic Id where applicable")
    logistic_details: Optional[str] = Field(..., description="logistic details")
    product: str = Field(..., description="product name")
    finished: bool = Field(..., description="True if your full objective has been achieved else False")
    
    def to_dict(self):
        return self.dict()
    
    
# Function to create structured Input
async def create_structured_input(sender: str, recipient: str, response: str, message: str, product_name: str,
                                  price: str, customer_id: str = None, business_id: Optional[str] = None, message_type: Optional[str]=""):
    structured_input = Input(
        sender=sender,
        recipient=recipient,
        response=response,
        message=message,
        product_name=product_name,
        price=price,
        customer_id=customer_id,
        business_id=business_id,
        message_type = message_type
    )
    return structured_input


# Function to create structured Response
async def create_structured_response(sender: str, recipient: str, customer_id: str, business_id: str, message: str,
                                     product: str, finished: bool, logistic_id: Optional[str] = "", logistic_details: Optional[str]="") -> Response:
    structured_response = Response(
        sender=sender,
        recipient=recipient,
        customer_id=customer_id,
        business_id=business_id,
        message=message,
        product=product,
        finished=finished,
        logistic_details = logistic_details,
        logistic_id=logistic_id 
    )
    return structured_response


# Function to create a structured Process object
async def create_structured_process(product_name: str,  task_type: str, price: Optional[str] = "",
                                    chat_history: Optional[Union[List[str], List[Tuple]]] = None, 
                                    # system_prompt: Optional[str] = "", 
                                    logistic_id: Optional[str] = "", 
                                    logistic_details: Optional[str] = "",
                                    customer_address: Optional[str]="") -> Process:
    structured_process = Process(
        product_name=product_name,
        price=price,
        communication_history=chat_history,
        task_type=task_type,
        # system_prompt=system_prompt,
        logistic_id=logistic_id,
        logistic_details=logistic_details,
        customer_address = customer_address
    )
    return structured_process


async def  get_chain_input_for_process(product="", customer_id="", business_id="", logistic_id="",
                                       customer_address= "", communication_history="", **kwargs):
    chain_input = {
        "product": product,
        "customer_id": customer_id, 
        "business_id": business_id,
        'communication_history': communication_history,
    }
    
    if logistic_id:
        chain_input["logistic_id"] = f"using logistic company with id:- {logistic_id}"
        
    if customer_address:
        chain_input["customer_address"] = customer_address
    else:
        chain_input["customer_address"] = "Not yet gotten from customer"
        
    if kwargs:
        chain_input.update(kwargs)
    return chain_input