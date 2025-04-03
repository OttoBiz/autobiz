from backend.db.cache_utils import test_redis_connection
import uvicorn
from fastapi import FastAPI, BackgroundTasks, Request   # , Depends
from backend.chatbot import *

from dotenv import load_dotenv
from backend.struct import *
from backend.chatbot.agents.interface.user_chat_interface import chat
from backend.chatbot.agents.interface.business_chat_interface import business_chat
import logging
import os
from backend.db.fake_data import load_csv_to_db
from backend.chatbot.agents.central_agent import run_central_agent
from backend.chatbot.agents.utils.central_agent import create_structured_input
from backend.chatbot.agents.product_agent import run_product_agent
from backend.chatbot.agents.upselling_agent import run_upselling_agent
from backend.chatbot.agents.payment_verification_agent import run_verification_agent
from backend.chatbot.agents.customer_complaint_agent import run_customer_complaint_agent
from backend.chatbot.agents.logistics_agent import run_logistics_agent
from backend.chatbot.agents.business_agent import run_business_agent
from backend.whatsapp.routers import router


load_dotenv()
LOG_FILE = os.getenv("LOG_FILE")
logging.basicConfig(filename=LOG_FILE, level=logging.WARNING,
                    format='%(asctime)s [%(levelname)s]: %(message)s')

# Create an instance of FastAPI
app = FastAPI()

PORT = os.getenv("PORT", 8000) 

# # Store dummy data in the database
# load_csv_to_db("./dummy_data/Business_table.csv", "businesses")
load_csv_to_db("./dummy_data/donrey_fashion.csv", "products")
# load_csv_to_db("./dummy_data/junae_cosmetics.csv", "products")
# load_csv_to_db("./dummy_data/manny_gadgets.csv", "products")
test_redis_connection()

@app.post("/chat")
async def get_chat_response(user_request: UserRequest, background_tasks: BackgroundTasks):
    response = await chat(user_request, background_tasks)
    return {"message": response}


@app.post("/business_chat") # For logistics and businesses as they are both businesses.
async def get_business_response(business_request: BusinessRequest, background_tasks: BackgroundTasks):
    response = await business_chat(business_request, background_tasks)
    return {"message": response}


@app.get("/")
async def health():
    return {"status": "ok"}


@app.post("/agent")
async def chat_agent(request: AgentRequest, background_tasks: BackgroundTasks):
    if request.agent == "central_agent":
        response = await run_central_agent(request.agent_input, background_tasks)
    elif request.agent == "product_agent":
        response = await run_product_agent(request.agent_input, background_tasks)
    elif request.agent == "upselling_agent":
        response = await run_upselling_agent(request.agent_input, background_tasks)
    elif request.agent == "customer_complaint_agent":
        response = await run_customer_complaint_agent(request.agent_input, background_tasks)
    else:
        response = await run_verification_agent(request.agent_input, background_tasks)
    return {"message": response}
        

# app.include_router(router=router)


# if __name__ == "__main__":
#     uvicorn.run(app, host="0.0.0.0", port=PORT, reload=True)
