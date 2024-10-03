from langchain_core.pydantic_v1 import BaseModel, Field
from typing import Optional, List, Union, Dict


class BaseSchema(BaseModel):
    """"""
    for_central_agent: bool = Field(
        ...,
        description="""
        if business's message is in response to details of an ongoing order or product enquiry
        entailing logistics, customer complaint, payment verification etc. True if it is, else False""",
    )
   
class BusinessEnquiry(BaseSchema):
    """Provide accurate information about business performance and inventory."""

    business_message: str = Field(..., description="business owner's request as standalone.")
    metrics: str = Field(..., description="Metrics business is interested in.")
    instruction: Optional[str] = Field(
        ...,
        description="Additonal instruction to be used to ensure better service to business.",
    )
    

class BusinessResponse(BaseSchema):
    """Provide accurate information about the business's response or feedback to customer order details, product details +/- logistic details being discussed."""

    business_message: str = Field(..., description="business owner's (vendor/logistic company) message as standalone.")
    product_name: str = Field(..., description="Name of product being discussed.")
    price: str = Field(..., description="product price")
    logistic_id: Optional[str] = Field(..., description="logistic id")
    business_id: str = Field(..., description='business_id')
    customer_id: str = Field(..., description="customer_id")
    message_type: str = Field(..., description=""""one of the following: ["Logistic planning", "Customer Feedback", "Product Unavailable",
                              "Payment Verification"]""")


arg_schema = [
    BusinessEnquiry,
    BusinessResponse
]
