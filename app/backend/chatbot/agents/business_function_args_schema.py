"""
Business Function Arguments Schema - Converted to Pydantic
"""
from pydantic import BaseModel, Field
from typing import Optional


class BaseSchema(BaseModel):
    """Base schema for business functions"""
    for_central_agent: bool = Field(
        ...,
        description="""If business's message is in response to details of an ongoing order or product enquiry
        entailing logistics, customer complaint, payment verification etc. True if it is, else False"""
    )


class BusinessEnquiry(BaseSchema):
    """Business enquiry schema"""
    business_message: str = Field(..., description="Business owner's request as standalone.")
    metrics: str = Field(..., description="Metrics business is interested in.")
    instruction: Optional[str] = Field(
        None,
        description="Additional instruction to be used to ensure better service to business."
    )


class BusinessResponse(BaseSchema):
    """Business response schema"""
    business_message: str = Field(..., description="Business owner's (vendor/logistic company) message as standalone.")
    product_name: str = Field(..., description="Name of product being discussed.")
    price: str = Field(..., description="Product price")
    logistic_id: Optional[str] = Field(None, description="Logistic id")
    business_id: str = Field(..., description="Business id")
    customer_id: str = Field(..., description="Customer id")
    message_type: str = Field(
        ...,
        description="""One of the following: ["Logistic planning", "Customer Feedback", "Product Unavailable", "Payment Verification"]"""
    )


arg_schema = [
    BusinessEnquiry,
    BusinessResponse
]
