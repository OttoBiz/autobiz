from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

class Customer(BaseModel):
    id: str
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None

class BankAccount(BaseModel):
    name: Optional[str] = None
    number: Optional[str] = None

class Vendor(BaseModel):
    id: str
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    bank_account: Optional[BankAccount] = None

class Logistics(BaseModel):
    id: str
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    bank_account: Optional[BankAccount] = None

class Product(BaseModel):
    id: str = ""
    name: str = ""
    quantity: int = 1
    price: float = 0.0
    has_paid: bool = False
    metadata: Optional[Dict[str, Any]] = None

class EntityType(str, Enum):
    CUSTOMER = "Customer"
    VENDOR = "Vendor"
    LOGISTICS = "Logistics"
    AGENT = "Agent"

class Task(BaseModel):
    name: str
    value: str
    
class TaskType(str, Enum):
    PRODUCT_ENQUIRY = "Product Enquiry"
    PAYMENT_VERIFICATION = "Payment Verification"
    LOGISTICS_ENQUIRY = "Logistics Enquiry"
    COMPLAINT = "Complaint"
    LOGISTICS_COORDINATION = "Logistics Coordination"
    UNKNOWN = "Unknown"
    
    
class CentralAgentInput(BaseModel):
    sender: EntityType
    recipient: EntityType
    business: Optional[Vendor] = None
    customer: Optional[Customer] = None
    logistic: Optional[Logistics] = None
    message: str
    product: Optional[Product] = None
    order_id: Optional[str] = None
    process_id: Optional[str] = None
    task_type: Optional[TaskType] = None

    def to_dict(self):
        return self.model_dump()

class ProductAgentInput(BaseModel):
    customer_message: str
    product_name: str
    product_category: str
    intent: Optional[str] = "enquiry"

class UpsellingAgentInput(BaseModel):
    product: str
    intent: Optional[str] = "inquired"
    conversation_messages: Optional[list] = []

class CustomerComplaintAgent(BaseModel):
    product_name: str
    customer_message: str
    customer_address: str
    miscellaneous: str
    customer_id: Optional[str] = "09071536199"
    business_id: str

class PaymentVerifcationAgent(BaseModel):
    product_name: str
    customer_id: Optional[str] = "09071536199"
    business_id: str
    product_price: str
    amount_paid: str
    customer_name: Optional[str] = "Bode Thomas"
    bank_account_number: Optional[str] = "120507869"
    bank_name: Optional[str] = "GTBank"

class UserRequest(BaseModel):
    user_id: str
    vendor_id: str
    session_id: str
    message: str
    msg_date_time: Optional[Union[datetime, str]] = None

class BusinessRequest(BaseModel):
    """Party sending the message: same `businesses.id` whether vendor, logistics, or service."""

    business_id: str
    session_id: str
    sender: str
    message: str
    msg_date_time: Optional[Union[datetime, str]] = None

class AgentRequest(BaseModel):
    user_id: str
    vendor_id: Optional[str] = None
    logistic_id: Optional[str] = None
    agent: str
    message: str
    agent_input: Optional[
        Union[
            CentralAgentInput,
            CustomerComplaintAgent,
            PaymentVerifcationAgent,
            UpsellingAgentInput,
            ProductAgentInput,
        ]
    ] = None
