from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel


class BankAccount(BaseModel):
    name: Optional[str] = None
    number: Optional[str] = None


class Logistics(BaseModel):
    id: str
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    bank_account: Optional[BankAccount] = None


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


class AgentRequest(BaseModel):
    user_id: str
    vendor_id: Optional[str] = None
    logistic_id: Optional[str] = None
    agent: str
    message: str
    agent_input: Optional[
        Union[
            CustomerComplaintAgent,
            PaymentVerifcationAgent,
            UpsellingAgentInput,
            ProductAgentInput,
        ]
    ] = None
