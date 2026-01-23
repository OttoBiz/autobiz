"""
User Function Arguments Schema - Converted to Pydantic
Used for routing and conversation stage determination
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Union, Dict


class ConversationStage(BaseModel):
    """Conversation stage schema"""
    conversation_stage: str = Field(
        ...,
        description="""Stage of conversation/sales process. Must be one of:
        - Product Enquiry: Information about products
        - Product purchase: Customer intends to purchase a product
        - Payment verification: Verify customer's payment for a particular product
        - Logistics: Delivery & logistic planning after successful payment verification
        - Ads Marketing: Upselling complimentary products to customer after successful logistic planning
        - Customer complaint/Feedback: [Refund, Faulty product]"""
    )


class ProductInfo(ConversationStage):
    """Product information schema"""
    customer_message: str = Field(..., description="Customer's message summarized")
    product_name: str = Field(
        ...,
        description="Product name. If cannot determine from customer's message or chat history, set to 'NONE'."
    )
    product_attributes: Optional[dict] = Field(
        None,
        description="Additional product attributes. A dictionary of key, value pairs of product attributes requested."
    )
    product_category: Optional[str] = Field(None, description="Product category e.g fashion")
    intent: str = Field(..., description="Customer's Intent: [enquiry, purchase]")
    instruction: Optional[str] = Field(
        None,
        description="Additional instruction to ensure better service to customer."
    )


class ProductInfoEvaluationOutput(BaseModel):
    """Product info evaluation output"""
    product_match: str = Field(
        ...,
        description="""If the product mentioned in customer's enquiry completely matches any product in the list of available products, return 'EXACT_MATCH'.
        If there is a partial or generic match return 'GENERIC_MATCH' else return 'NO_MATCH'."""
    )
    product_attribute_enquiry: Optional[Union[List[str], None]] = Field(
        None,
        description="List of specific product attributes to confirm from customer to finetune results. Set to None if EXACT_MATCH."
    )
    available_products: List = Field(
        ...,
        description="A list of **unique** products and its respective information gotten from the list of available products that completely or partially matched the product the customer enquires about."
    )
    instruction: str = Field(..., description="Next course of action for product agent to carry out.")


class PaymentVerification(ConversationStage):
    """Payment verification schema"""
    product_name: str = Field(..., description="Product purchased by customer.")
    product_price: str = Field(..., description="Product's price provided by vendor assistant not customer.")
    amount_paid: str = Field(..., description="Amount paid by customer.")
    customer_name: str = Field(..., description="Customer's account full name")
    bank_account_number: str = Field(..., description="Bank account number.")
    bank_name: str = Field(..., description="Bank Name.")
    customer_message: str = Field(..., description="Customer message as standalone message.")


class AdsMarketing(ConversationStage):
    """Ads marketing/upselling schema"""
    product: str = Field(..., description="Index product just purchased by customer")
    product_category: str = Field(..., description="Product's category")
    intent: str = Field(..., description="Customer's intent: ['purchased', 'inquired']")


class Logistics(ConversationStage):
    """Logistics schema"""
    product_name: Optional[str] = Field(None, description="Product name")
    customer_message: str = Field(..., description="Customer's message as standalone")
    customer_address: str = Field(..., description="Customer's address for product delivery")
    miscellaneous: Optional[str] = Field(default="", description="Other important info to help with delivery e.g convenient time for delivery")


class CustomerComplaint(ConversationStage):
    """Customer complaint schema"""
    product_name: Optional[str] = Field(None, description="Product name")
    complaint: str = Field(..., description="Customer's complaint or message as standalone")
    sentiment: Optional[str] = Field(None, description="Customer sentiment.")
    product_rating: Optional[str] = Field(None, description="Estimated rating of product [1 - 10]")
    order_no: str = Field(..., description="Purchase order number.")
    Date: Optional[str] = Field(None, description="Date item was purchased.")


# Legacy export for backward compatibility
arg_schema = [
    ProductInfo,
    PaymentVerification,
    Logistics,
    AdsMarketing,
    CustomerComplaint,
]
