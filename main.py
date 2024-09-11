import uvicorn
from fastapi import FastAPI, BackgroundTasks, Request   # , Depends
from backend.chatbot import *

from dotenv import load_dotenv
from backend.struct import *
from backend.chatbot.agents.bot import chat
import logging
import os
from backend.db.fake_data import load_csv_to_db
from backend.chatbot.agents.central_agent import run_central_agent
from backend.chatbot.agents.central_agent_utils import create_structured_input
from backend.chatbot.agents.product_agent import run_product_agent
from backend.chatbot.agents.upselling_agent import run_upselling_agent
from backend.chatbot.agents.payment_verification_agent import run_verification_agent


load_dotenv()
LOG_FILE = os.getenv("LOG_FILE")
logging.basicConfig(filename=LOG_FILE, level=logging.WARNING,
                    format='%(asctime)s [%(levelname)s]: %(message)s')

##manny: 2347000000001, junae_cosmetics: 2347000000002, donrey:2347000000003, davidfurnitures:2347000000004, 
# wakaso logistics :2347000000005, mega_deliver :2347000000006, perodont: 2347000000007, getwell: 2347000000008, blueteams: 2347000000009

# Create an instance of FastAPI
app = FastAPI()

# Store dummy data in the database
# load_csv_to_db("./dummy_data/Business_table.csv", "businesses")
# load_csv_to_db("./dummy_data/donrey_fashion.csv", "products")
# load_csv_to_db("./dummy_data/junae_cosmetics.csv", "products")
# load_csv_to_db("./dummy_data/manny_gadgets.csv", "products")

@app.post("/chat")
async def get_chat_response(user_request: UserRequest):
    response = await chat(user_request)
    return {"message": response}


@app.get("/")
async def health():
    return {"status": "ok"}


@app.post("/agent")
async def chat_agent(request: AgentRequest):
    if request.agent == "central_agent":
        response = await run_central_agent(request.agent_input)
    elif request.agent == "product_agent":
        response = await run_product_agent(request.agent_input)
    elif request.agent == "upselling_agent":
        response = await run_upselling_agent(request.agent_input)
    else:
        response = await run_verification_agent(request.agent_input)
    return {"message": response}
        


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
