"""
Central Agent Utilities
Converted to use Pydantic instead of LangChain
"""
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field


class CentralAgentInput(BaseModel):
    """Input for central agent"""
    sender: str  # ["Agent", "Customer", "Vendor", "Logistics"]
    recipient: str
    business_id: Optional[str] = ""
    customer_id: Optional[str] = ""
    logistic_id: Optional[str] = ""
    message: str
    product_name: str
    price: Optional[str] = None
    message_type: Optional[str] = None  # ["Logistic planning", "Customer Feedback", "Product Unavailable", "Payment Verification"]
    customer_address: Optional[str] = None
    customer_bank_details: Optional[str] = ""


class customer(BaseModel):
    id: str
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None

class BankAccount(BaseModel):
    name: Optional[str] = None
    number: Optional[str] = None
    name: Optional[str] = None
    
class Vendor(BaseModel):
    id: str
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    bank_account: BankAccount
    
class Logistics(BaseModel):
    id: str
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    

class Product(BaseModel):
    id: str
    name: str
    quantity: int
    price: float
    metadata: Optional[Dict[str, Any]] = None
    
class Process(BaseModel):
    """Process model for central agent"""
    communication_history: Optional[List[Dict[str, Any]]] = None
    task_type: str
    customer_address: Optional[str] = ""
    customer: customer
    vendor: Vendor
    logistics: Logistics
    id: str


async def create_structured_input(
    sender: str,
    recipient: str,
    message: str,
    product_name: str,
    price: str,
    customer_id: Optional[str] = None,
    business_id: Optional[str] = None,
    customer_address: str = "",
    bank_details: str = "",
    message_type: Optional[str] = "",
    logistic_id: Optional[str] = None
) -> CentralAgentInput:
    """Create structured input for central agent"""
    return CentralAgentInput(
        sender=sender,
        recipient=recipient,
        message=message,
        product_name=product_name,
        price=price,
        customer_id=customer_id,
        business_id=business_id,
        message_type=message_type,
        customer_address=customer_address,
        customer_bank_details=bank_details,
        logistic_id=logistic_id
    )


async def create_structured_process(
    product_name: str,
    task_type: str,
    price: Optional[str] = "",
    chat_history: Optional[List[Dict[str, Any]]] = None,
    logistic_id: Optional[str] = "",
    logistic_details: Optional[str] = "",
    customer_address: Optional[str] = ""
) -> Process:
    """Create structured process"""
    return Process(
        product_name=product_name,
        price=price,
        communication_history=chat_history or [],
        task_type=task_type,
        logistic_id=logistic_id,
        logistic_details=logistic_details,
        customer_address=customer_address
    )
