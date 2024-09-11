from .central_agent import run_central_agent
from .central_agent_utils import create_structured_input


async def run_logistics_agent(product_name, customer_message, customer_address, miscellaneous, **kwargs):
    #sentiment, product_rating, date can be added as arguments to improve recommendations and user experience.

    customer_address += f"\nAdditional Information: {miscellaneous}"
    agent_input = await create_structured_input(sender="customer", recipient="vendor", message=customer_message, product_name=product_name,
                                  price= kwargs.get("price", ""), customer_id= kwargs.get("customer_id"), 
                                  business_id = kwargs.get("business_id"), customer_address=customer_address, message_type="Logistic planning")
        
    
    #Structure input in the way central agent will use it.
    response = await run_central_agent(agent_input)
    
    # Move on to Logistics from here.
    
    return response.message