from langchain_core.pydantic_v1 import BaseModel, Field
from typing import Optional, List, Union, Dict


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
   


class ProductInfo(BaseSchema):
    """Provide accurate information about the product enquiries."""

    customer_message: str = Field(..., description="Customer's need summarized.")
    product_name: str = Field(..., description="Product name. if you cannot determine any form of product name from the customer's message, set to 'NONE'.")
    product_attributes: Optional[dict] = Field(
        ...,
        description="Additional product attribute. A dictionary of key, value pairs of product attribute requested."
    )
    product_category: Optional[str] = Field(
        ..., description="product category e.g fashion"
    )
    intent: str = Field(..., description="Customer's Intent: [enquiry, purchase]")
    instruction: Optional[str] = Field(
        ...,
        description="Additonal instruction to be used to ensure better service to customer.",
    )
   

class ProductInfoEvaluationOutput(BaseModel):
   
    product_match: str = Field(..., description="""if the product mentioned in the customer's enquiry completely matches any product in the list of available products, return 'EXACT_MATCH'
                               if there is a partial or generic match return 'GENERIC_MATCH' else return 'NO_MATCH'.""")
    
    product_attribute_enquiry: Optional[Union[List[str], None]] = Field(
        ..., description="List of specific product attributes to confirm from the customer to finetune results. Set to None if EXACT_MATCH."
    )
    available_products: List = Field(...,
             description="""A list of **unique** products and its respective information gotten from the list of available products that completely or partially matched the product
             the customer enquires about.""" 
        )
    instruction: str = Field(..., description="Next course of action for product agent to carry out.")

class PaymentVerification(BaseSchema):
    """Provide accurate details about a payment transaction for verification based on recent chat history.
    Ask customer to provide all necessary fields if any is missing. if no product was previously discussed, politely decline verification
    and state your reasons to customer"""

    product_name: str = Field(..., description="Product purchased by customer.")
    product_price: str = Field(..., description= "Product's price provided by vendor assistant not customer.")
    amount_paid: str = Field(..., description="Amount paid by customer.")
    customer_name: str = Field(..., description="customer's account full name")
    bank_account_number: str = Field(..., description="Bank account number.")
    bank_name: str = Field(..., description="Bank Name.")
    customer_message: str= Field(..., description='customer message as standalone message.')



class AdsMarketing(BaseSchema):
    """To determine complimentary products that can be marketed to customer given index purchase. You call this function after a user has finished 
    purchasing an item and you want to upsell a complimentary product."""
    product_purchased: str = Field(..., description="index product purchased by customer")
    product_category: str = Field(
        ..., description="Product's category e.g Fashion, health etc"
    )
   

class CentralAgentBase(BaseSchema):
    product_name: Optional[str] = Field(..., description="product name")

class Logistics(CentralAgentBase):
    """Provide information about delivery logistics."""
    customer_message: str = Field(..., description="customer's message as standalone")
    customer_address: str = Field(
        ..., description="customer's address for product delivery")
    
    miscellaneous: str = Field(..., description="other important info to help with delivery e.g convenient time for delivery")
    
class CustomerComplaint(CentralAgentBase):
    """Provide information about customer's complaint"""
    complaint: str = Field(..., description="customer's complaint or message as standalone")
    
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
