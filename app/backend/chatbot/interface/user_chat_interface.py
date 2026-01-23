"""
User Chat Interface - Main entry point for customer conversations
Updated to use pydantic_ai
"""
from fastapi import BackgroundTasks
from .routing_agent import route_conversation
from .product_agent import run_product_agent
from .upselling_agent import run_upselling_agent
from .payment_verification_agent import run_verification_agent
from .customer_complaint_agent import run_customer_complaint_agent
from .logistics_agent import run_logistics_agent
from .evaluator_agent import evaluate_response, should_send_response
from .agent_utils import get_or_create_user_state, save_user_state, format_chat_history
from backend.db.db_utils import get_business_info
from backend.struct import UserRequest


async def chat(
    user_request: UserRequest,
    background_tasks: BackgroundTasks = None,
    reset_user_state: bool = False,
    debug: bool = False
) -> str:
    """
    Main chat function that routes customer messages to appropriate agents.
    
    Args:
        user_request: User request with message and IDs
        background_tasks: Background tasks for async operations
        reset_user_state: Whether to reset user state (for testing)
        debug: Debug mode
        
    Returns:
        Response message from the appropriate agent
    """
    # Get or create user state
    user_state = await get_or_create_user_state(
        user_request.user_id,
        user_request.vendor_id
    )
    
    if debug:
        print(f"User state: {user_state}")
    
    chat_history = user_state.get("chat_history", [])
    
    # Route conversation to determine which agent to use
    routing = await route_conversation(
        message=user_request.message,
        chat_history=chat_history,
        business_id=user_request.vendor_id,
        user_id=user_request.user_id
    )
    
    if debug:
        print(f"Routing result: {routing}")
    
    # Route to appropriate agent based on conversation stage
    stage = routing.stage
    
    if stage == "Product Enquiry" or stage == "Product purchase":
        # Use product agent
        response, user_state = await run_product_agent(
            customer_message=user_request.message,
            product_name=routing.product_name or "NONE",
            product_category=routing.product_category or "",
            intent=routing.intent or "enquiry",
            user_id=user_request.user_id,
            business_id=user_request.vendor_id,
            user_state=user_state,
            debug=debug
        )
        
    elif stage == "Payment verification":
        # Use payment verification agent
        response = await run_verification_agent(
            customer_message=user_request.message,
            user_id=user_request.user_id,
            business_id=user_request.vendor_id,
            user_state=user_state,
            background_tasks=background_tasks,
            debug=debug
        )
        
    elif stage == "Logistics":
        # Use logistics agent
        response = await run_logistics_agent(
            customer_message=user_request.message,
            user_id=user_request.user_id,
            business_id=user_request.vendor_id,
            user_state=user_state,
            background_tasks=background_tasks,
            debug=debug
        )
        
    elif stage == "Ads Marketing":
        # Use upselling agent
        response = await run_upselling_agent(
            product=routing.product_name or "",
            intent="purchased",
            business_id=user_request.vendor_id
        )
        # Update user state
        user_state["chat_history"].append({
            "role": "user",
            "name": "customer",
            "content": user_request.message
        })
        user_state["chat_history"].append({
            "role": "assistant",
            "name": "upselling_agent",
            "content": response
        })
        
    elif stage == "Customer complaint/Feedback":
        # Use customer complaint agent
        response, user_state = await run_customer_complaint_agent(
            complaint=user_request.message,
            product_name=routing.product_name or "",
            user_id=user_request.user_id,
            business_id=user_request.vendor_id,
            user_state=user_state,
            background_tasks=background_tasks,
            debug=debug
        )
        
    else:
        # General conversation - use product agent as fallback
        response, user_state = await run_product_agent(
            customer_message=user_request.message,
            product_name="NONE",
            product_category="",
            intent="enquiry",
            user_id=user_request.user_id,
            business_id=user_request.vendor_id,
            user_state=user_state,
            debug=debug
        )
    
    # Evaluate response before sending
    conversation_context = format_chat_history(user_state.get("chat_history", []))
    evaluation = await evaluate_response(response, conversation_context)
    
    if not evaluation.should_send:
        # Use improved response if evaluation suggests
        if evaluation.suggested_improvement:
            response = evaluation.suggested_improvement
        else:
            response = "I apologize, let me rephrase that. " + response
    
    # Save user state (unless resetting for testing)
    if not reset_user_state:
        await save_user_state(
            user_request.user_id,
            user_request.vendor_id,
            user_state
        )
    
    return response
