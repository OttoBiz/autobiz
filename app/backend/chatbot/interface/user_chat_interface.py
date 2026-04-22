"""
User Chat Interface - Main entry point for customer conversations
Updated to use pydantic_ai with file handling support
"""
from fastapi import BackgroundTasks, UploadFile
from typing import List, Optional, Dict, Any
from backend.chatbot.agents.routing_agent import route_conversation
from backend.chatbot.agents.product import run_product_agent
from backend.chatbot.agents.upselling_agent import run_ads_marketing_agent, run_upselling_agent
from backend.chatbot.agents.payment import run_verification_agent
from backend.chatbot.agents.customer_relation import run_customer_complaint_agent
from backend.chatbot.agents.logistics import run_logistics_agent
from backend.chatbot.agents.evaluator_agent import evaluate_response, should_send_response
from backend.chatbot.utils.agent_utils import get_or_create_user_state, save_user_state, format_chat_history
from backend.chatbot.utils.file_handler import process_uploaded_files
from backend.db.db_utils import get_business_info
from backend.struct import UserRequest
from backend.db.cache_utils import get_user_state, modify_user_state
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)


async def chat(
    user_request: UserRequest,
    background_tasks: BackgroundTasks = None,
    reset_user_state: bool = False,
    debug: bool = False,
    files: Optional[List[UploadFile]] = None
) -> str:
    """
    Main chat function that routes customer messages to appropriate agents.
    
    Args:
        user_request: User request with message and IDs
        background_tasks: Background tasks for async operations
        reset_user_state: Whether to reset user state (for testing)
        debug: Debug mode
        files: Optional list of uploaded files
        
    Returns:
        Response message from the appropriate agent
    """
    # Get or create user state
    user_state = await get_user_state(
        user_request.user_id,
        user_request.vendor_id
    )
    
    if debug:
        print(f"User state: {user_state}")
    
    chat_history = user_state.get("chat_history", [])
    
    # Process files if provided
    file_content_summary = "*Uploaded Files By User"
    receipt_data = None
    
    if files:
        # Get product info from user state for receipt verification
        products_cache = user_state.get("products", {})
        expected_product = None
        expected_amount = None
        
        # Try to get latest product info
        if products_cache:
            latest_product = list(products_cache.values())[0]
            products = latest_product.get("retrieved_results", [])
            if products:
                expected_product = products[0].get("name") or products[0].get("product_name")
                expected_amount = products[0].get("price")
        
        # Process files
        processed_files = await process_uploaded_files(
            files,
            user_request.vendor_id,
            user_request.user_id,
            expected_product=expected_product,
            expected_amount=expected_amount
        )
        
        # Save processed files to user state
        user_state.setdefault("uploaded_files", []).extend(processed_files)
        
        # Extract receipt data if available
        for file_result in processed_files:
            if file_result.get("extracted_content"):
                file_content_summary += f"\nFile '{file_result['filename']}': {file_result['extracted_content']}"
                
                # Check if it's a receipt
                if "receipt" in file_result.get("filename", "").lower() or "payment" in file_result.get("filename", "").lower():
                    receipt_data = file_result.get("extracted_content")
                    user_state["receipt_data"] = receipt_data
    
    # Combine message with file content
    full_message = user_request.message
    if file_content_summary:
        full_message += "\n\n" + file_content_summary
    
    business_name = (user_state.get("business_information") or {}).get("name")
    if not business_name:
        biz = await get_business_info(user_request.vendor_id)
        business_name = (biz or {}).get("name")
        if biz:
            user_state.setdefault("business_information", {}).update(biz)

    processes = user_state.get("processes", {})
    order_context = ", ".join(
        f"{pname} -> {p.get('order_id', '')}"
        for pname, p in processes.items()
        if isinstance(p, dict) and p.get("order_id")
    ) or None

    routing = await route_conversation(
        message=full_message,
        chat_history=chat_history,
        business_id=user_request.vendor_id,
        user_id=user_request.user_id,
        business_name=business_name,
        order_context=order_context,
    )
    
    if debug:
        print(f"Routing result: {routing}")
    
    # Route to appropriate agent based on conversation stage
    stage = routing.stage
    print(f"Conversation Stage: {stage}")
    print(f"Routing: {routing}")
    
    if stage == "Product Enquiry" or stage == "Product purchase":
        # Use product agent
        response, user_state = await run_product_agent(
            customer_message=full_message,
            product_name=routing.product_name or "NONE",
            product_category=routing.product_category or "",
            intent=routing.intent or "enquiry",
            user_id=user_request.user_id,
            business_id=user_request.vendor_id,
            user_state=user_state,
            debug=debug
        )
        
    elif stage == "Payment verification" or receipt_data:
        response = await run_verification_agent(
            customer_message=full_message,
            user_id=user_request.user_id,
            business_id=user_request.vendor_id,
            product_name=routing.product_name or None,
            user_state=user_state,
            background_tasks=background_tasks,
            receipt_data=receipt_data,
            order_id=routing.order_id,
            debug=debug,
        )
        
    elif stage == "Logistics":
        response = await run_logistics_agent(
            customer_message=full_message,
            user_id=user_request.user_id,
            business_id=user_request.vendor_id,
            product_name=routing.product_name or None,
            user_state=user_state,
            background_tasks=background_tasks,
            order_id=routing.order_id,
            debug=debug,
        )
        
    elif stage == "Customer complaint/Feedback":
        response, user_state = await run_customer_complaint_agent(
            complaint=full_message,
            product_name=routing.product_name or "",
            user_id=user_request.user_id,
            business_id=user_request.vendor_id,
            user_state=user_state,
            background_tasks=background_tasks,
            debug=debug
        )

    elif stage == "Ads Marketing":
        response = await run_ads_marketing_agent(
            customer_message=full_message,
            product_name=routing.product_name,
            business_id=user_request.vendor_id,
            user_state=user_state,
        )
        user_state.setdefault("chat_history", []).extend([
            ModelRequest(parts=[UserPromptPart(content=user_request.message)]),
            ModelResponse(parts=[TextPart(content=response)]),
        ])

    else:
        response = routing.response
        user_state.setdefault("chat_history", []).extend([
            ModelRequest(parts=[UserPromptPart(content=user_request.message)]),
            ModelResponse(parts=[TextPart(content=response)]),
        ])
        
    # Save user state (unless resetting for testing)
    if not reset_user_state:
        await modify_user_state(
            user_request.user_id,
            user_request.vendor_id,
            user_state
        )
    
    return response
