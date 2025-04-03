from langchain_core.pydantic_v1 import BaseModel, Field
from typing import Optional, List, Union, Dict


class BaseSchema(BaseModel):
    """"""
    for_central_agent: bool = Field(
        ...,
        description="""
        if business's message is in response to an ongoing order, product enquiry, customer complaint, 
        payment verification etc. Return 'True' if it is, else 'False'. No additional statements.""",
    )
    business_message: str = Field(..., description="business owner's request/message as standalone.")
    
   
class BusinessEnquiry(BaseSchema):
    """Provide accurate information about business performance and inventory."""
    
    metrics: Union[List[str], str] = Field(..., description="Metrics owner is interested in.")
    instruction: Optional[str] = Field(
        ...,
        description="Additonal instruction for better response.",
    )
    

class BusinessResponse(BaseSchema):
    """Provide accurate information about the business's response or feedback to customer order details, product details +/- logistic details being discussed."""
    product_name: str = Field(..., description="Name of product being discussed.")
    product_price: str = Field(..., description="product price")
    customer_id: str = Field(..., description="customer id")
    logisitic_id: str = Field(..., description="logistic id")
    task_type: str = Field(..., description=""""one of the following: ["Logistic planning", "Customer Feedback", "Product Unavailable",
                              "Payment Verification"]""")
    recipient: str = Field(
        ..., description="""
        Recipient of the message. This is typically directed to the customer, logistic or vendor."""
    )


arg_schema = [
    BusinessEnquiry,
    BusinessResponse
]
