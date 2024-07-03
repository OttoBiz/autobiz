import uvicorn
from fastapi import FastAPI  # , Depends

from backend.chatbot import *

# from backend.chatbot.utils import generate_qa
# from backend.chatbot.prompts.prompt import q_a_prompt

from dotenv import load_dotenv
from backend.struct import *
from backend.chatbot.agents.bot import chat


load_dotenv()

# Create an instance of FastAPI
app = FastAPI()


@app.post("/chat")
async def get_chat_response(user_request: UserRequest):
    response = await chat(user_request)
    print(response)
    return {"message": response}


@app.get("/")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
