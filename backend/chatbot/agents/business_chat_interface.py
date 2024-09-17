from backend.db.cache_utils import get_user_state, modify_user_state, delete_user_state
from backend.db.db_utils import *
from .central_agent import run_central_agent
from .central_agent_utils import create_structured_input

async def business_chat(user_request, debug=False):
    response = ""
    return response