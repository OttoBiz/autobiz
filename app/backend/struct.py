from pydantic import BaseModel
from typing import Optional, Dict, Union, Any
from datetime import datetime


class customer(BaseModel):
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
    id: str
    name: str
    quantity: int
    price: float
    has_paid: bool = False
    metadata: Optional[Dict[str, Any]] = None

class CentralAgentInput(BaseModel):
    """Input for central agent"""
    sender: str  # ["Agent", "Customer", "Vendor", "Logistics"]
    recipient: str # ["Agent", "Customer", "Vendor", "Logistics"]
    business: Optional[Vendor] =None
    customer: Optional[customer] =None
    logistic: Optional[Logistics] =None
    message: str
    product: Optional[Product] =None

    
    def to_dict(self):
        return self.dict()
    
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
    user_id: str
    vendor_id: str
    logistic_id: str
    session_id: str
    sender: str
    message: str
    product_name: str
    product_price: Optional[str]
    message_type: str
    msg_date_time: Optional[Union[datetime, str]] = None
    
class AgentRequest(BaseModel):
    user_id: str
    vendor_id: Optional[str] = None
    logistic_id: Optional[str] = None
    agent: str
    message: str
    agent_input: Optional[Union[CentralAgentInput, CustomerComplaintAgent, PaymentVerifcationAgent, UpsellingAgentInput, ProductAgentInput]] = None
