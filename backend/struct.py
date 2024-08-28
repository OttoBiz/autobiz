from pydantic import BaseModel
from typing import Optional, Dict, Union
from datetime import datetime

class Input(BaseModel):
    sender_type: str  #["Agent", "Customer", "Vendor", "Logistics"]
    sender: str
    recipient: str
    business_id: Optional[str] = None
    customer_id: Optional[str]
    message: str
    product_name: str
    price: str
    message_type: str  #["Logistic planning", "Customer Feedback", "Product Unavailable"]
    
    def to_dict(self):
        return self.dict()
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
    msg_date_time: Optional[Union[datetime, str]] = None
    agent_input: Optional[Input] = None
