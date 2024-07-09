from langchain_core.pydantic_v1 import BaseModel, Field
from typing import Optional


class BaseSchema(BaseModel):
    """"""

    conversation_stage: str = Field(
        ...,
        description="""stage of conversation/sales process. It must be one of the following:
                                    - Product Enquiry: Information about products.
                                    - Product purchase: Customer's intent to purchase a product.
                                    - Payment verification: Verify customer's payment for a particular product.
                                    - Logistics: Logistic planning after successful payment verification.
                                    - Ads Marketing: The last stage after successful product purchase and payment verification.
                                    - Customer complaint/Feedback: [Refund, Faulty product]""",
    )
    tone: str = Field(
        ...,
        description="The best tone and style to use in communication given customer's message to maintain engagement.",
    )


class ProductInfo(BaseSchema):
    """Provide accurate information about the product enquiries."""

    customer_message: str = Field(..., description="Customer's need summarized.")
    product_name: str = Field(..., description="Product name.")
    miscellaneous: Optional[str] = Field(
        ...,
        description="Additional info about the product as a list of ',' separated values",
    )
    product_category: Optional[str] = Field(
        ..., description="product category e.g fashion, furniture etc"
    )
    intent: str = Field(..., description="Customer's Intent: [enquiry, purchase]")
    instruction: Optional[str] = Field(
        ...,
        description="Additonal instruction to be used to ensure better service to customer.",
    )
    use_internet: bool = Field(
        ...,
        description="Whether to use internet to fetch information about product description",
    )


class PaymentVerification(BaseSchema):
    """Provide accurate details about a payment transaction for verification."""

    product_name: str = Field(..., description="Product purchased.")
    amount_paid: str = Field(..., description="Amount paid by user.")
    customer_name: str = Field(..., description="customer's full name")
    bank_account_number: str = Field(..., description="Bank account number.")
    bank_name: str = Field(..., description="Name of bank used for payment.")


class Logistics(BaseSchema):
    """Provide information about delivery logistics."""

    customer_address: str = Field(
        ..., description="The customer's address for product delivery"
    )


class AdsMarketing(BaseSchema):
    """Determine other products or accessories that can be sold to user given customers recent purchase."""

    product_purchased: str = Field(..., description="product purchased by customer")
    product_category: str = Field(
        ..., description="Product's category e.g Fashion, health etc"
    )
    accessory: str = Field(
        ...,
        description="A list of 3 other products or accessories that are typically purchased or used alongside the item purchased by customer.",
    )


class CustomerComplaint(BaseSchema):
    """Provide information about the complaint by user"""

    complaint: str = Field(..., description="customer's complaint summarized")
    product_name: Optional[str] = Field(..., description="product name")
    sentiment: Optional[str] = Field(
        ..., description="customer sentiment about product."
    )
    product_rating: Optional[str] = Field(
        ...,
        description="Estimated rating of product based on customer message [1 - 10]",
    )
    Date: Optional[str] = Field(..., description="Date item was purchased.")


arg_schema = [
    ProductInfo,
    PaymentVerification,
    Logistics,
    AdsMarketing,
    CustomerComplaint,
]
