from .central_agent import run_central_agent
from .utils.central_agent import create_structured_input
from fastapi import BackgroundTasks


async def run_logistics_agent(product_name, customer_message, customer_address, miscellaneous, background_tasks: BackgroundTasks,
                              **kwargs):
    
    is_first_call = kwargs["user_state"].get("first_logistic_call", True)

    customer_address += (f"\nAdditional Information: {miscellaneous}" if miscellaneous else "")
    
    #Structure input in the way central agent will use it.
    agent_input = await create_structured_input(sender="customer", recipient="vendor +/- logistic", message=customer_message, product_name=product_name,
                                  price= kwargs.get("price", ""), customer_id= kwargs.get("customer_id"), 
                                  business_id = kwargs.get("business_id"), customer_address=customer_address, task_type="Logistic planning")
  
    # response = await run_central_agent(agent_input, kwargs["user_state"])
    
    if is_first_call:
        kwargs["user_state"].set("first_logistic_call", False)
        # Add the central agent execution as a background task.
        background_tasks.add_task(run_central_agent, agent_input, kwargs["user_state"])
        return f"Please, hold on why we work on the logistics around delivery."
        
    else:
        # Add the central agent execution as a background task.
        background_tasks.add_task(run_central_agent, agent_input, kwargs["user_state"])
        return f"Please, hold on why we work out further details.", kwargs["user_state"]