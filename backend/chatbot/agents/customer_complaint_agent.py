from .central_agent import run_central_agent
from .central_agent_utils import create_structured_input



async def run_customer_complaint_agent(complaint, product_name,  **kwargs):
    #sentiment, product_rating, date can be added as arguments to improve recommendations and user experience.

     #Structure input in the way central agent will use it.
    agent_input = await create_structured_input(sender="customer", recipient="vendor", message=complaint, product_name=product_name,
                                  price= kwargs.get("price", ""), customer_id= kwargs.get("customer_id"), 
                                  business_id = kwargs.get("business_id"), message_type="Customer Feedback")
        
    
   
    response = await run_central_agent(agent_input, kwargs["user_state"])
    
    # Move on to Logistics from here.
    
    return response