"""
Central Agent Utilities
Converted to use Pydantic instead of LangChain
"""
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field
from backend.struct import CentralAgentInput, Customer, Vendor, Logistics, Product

class Process(BaseModel):
    """Process model for central agent"""
    communication_history: Optional[List[Dict[str, Any]]] = None
    finished_tasks: Optional[List[str]] = None
    task_type: str
    customer: Customer
    vendor: Vendor
    product: Product
    logistics: Logistics
    id: str


async def create_structured_input(
    sender: str,
    recipient: str,
    message: str,
    product: Optional[Product] =None,
    customer: Optional[Customer] = None,
    business: Optional[Vendor] = None,
    logistic: Optional[Logistics] = None
) -> CentralAgentInput:
    """Create structured input for central agent"""
    return CentralAgentInput(
        sender=sender,
        recipient=recipient,
        message=message,
        product=product,
        customer=customer,
        business=business,
        logistic=logistic
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
