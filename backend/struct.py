from pydantic import BaseModel
from typing import Optional, Dict, Union
from datetime import datetime


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
