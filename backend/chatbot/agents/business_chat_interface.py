from backend.db.db_utils import *
from .central_agent import run_central_agent
from .central_agent_utils import create_structured_input


async def business_chat(business_request, debug=False):
    
    agent_input = await create_structured_input(sender=business_request.sender, recipient="agent", message=business_request.message, 
                                                product_name=business_request.product_name, price= business_request.product_price, 
                                                customer_id= business_request.user_id, business_id = business_request.vendor_id,
                                                logistic_id = business_request.logistic_id, message_type=business_request.message_type,
                                    )
        
    response = await run_central_agent(agent_input)
    
    return response
