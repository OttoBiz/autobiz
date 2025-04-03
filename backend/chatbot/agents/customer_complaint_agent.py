from .central_agent import run_central_agent
from .utils.central_agent import create_structured_input
from fastapi import BackgroundTasks


async def run_customer_complaint_agent(complaint, product_name, background_tasks: BackgroundTasks, **kwargs):
    #sentiment, product_rating, date can be added as arguments to improve recommendations and user experience.

    #Structure input in the way central agent will use it.
    agent_input = await create_structured_input(sender="customer", recipient="vendor", message=complaint, product_name=product_name,
                                  price= kwargs.get("price", ""), customer_id= kwargs.get("customer_id"), 
                                  business_id = kwargs.get("business_id"), task_type="Customer Feedback")
   
    # Add the central agent execution as a background task.
    background_tasks.add_task(run_central_agent, agent_input, kwargs["user_state"])

    # Return a placeholder message to customer.

    return "Please, hold on while I process your message. \nI will get back to you shortly.", kwargs['user_state']