from .central_agent import run_central_agent
from .central_agent_utils import create_structured_input

async def run_verification_agent(product_name, product_price, amount_paid, customer_name, 
                                 bank_account_number, bank_name, **kwargs):
     
    customer_message = f"""I have made payments for the product. Here are my bank details to confirm transaction:
                        Bank name: {bank_name}
                        Bank account number: {bank_account_number}
                        Account name: {customer_name}
                        Amount paid: {amount_paid}"""
                        
    agent_input = await create_structured_input(sender="customer", recipient="vendor", message=customer_message, product_name=product_name,
                                  price= product_price, customer_id= kwargs["customer_id"], business_id = kwargs["business_id"], message_type="Payment verification")
        
    
    #Structure input in the way central agent will use it.
    response = await run_central_agent(agent_input)
    
    # Move on to Logistics from here.
    
    return response.message