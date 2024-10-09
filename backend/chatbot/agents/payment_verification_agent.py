from .central_agent import run_central_agent
from .central_agent_utils import create_structured_input
from fastapi import BackgroundTasks

async def run_verification_agent(product_name, product_price, amount_paid, customer_name, 
                                 bank_account_number, bank_name, customer_message, **kwargs):
    
    is_first_call = kwargs["user_state"].get("first_verification_call", True)
    
    # Process customer's bank details.
    customer_bank_details = f"""
                            **Purchase bank details**
                            Bank name: {bank_name}
                            Account:  {bank_account_number}
                            Name: {customer_name}
                            Amount paid: {amount_paid}
                        """
           
    # Structure input in the way central agent will use it.             
    agent_input = await create_structured_input(sender="customer", recipient="vendor", message=customer_message, product_name=product_name,
                                  price= product_price, customer_id= kwargs["customer_id"], business_id = kwargs["business_id"], logistic_id = kwargs["logistic_id"], message_type="Payment verification",
                                  bank_details = customer_bank_details)
        
    
    background_tasks = kwargs["background_tasks"]
   
    # await run_central_agent(agent_input, kwargs["user_state"])
    # Return a placeholder message to customer.
    if is_first_call:
        kwargs["user_state"]["first_verification_call"] = False
        # Add the central agent execution as a background task.
        background_tasks.add_task(run_central_agent, agent_input, kwargs["user_state"])
    
        
        return f"Please, hold while we verify payment for this product: {product_name}." , kwargs["user_state"]
    else:
        # Add the central agent execution as a background task.
        background_tasks.add_task(run_central_agent, agent_input, kwargs["user_state"])
    
        return "Please, hold on while we process your message. I will get back to you shortly.", kwargs['user_state']