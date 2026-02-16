"""
File Handler - Handles file uploads and processing
"""
import os
import uuid
from typing import List, Dict, Any, Optional
from fastapi import UploadFile
from backend.chatbot.utils.file_processor import process_file
from backend.chatbot.agents.media_processing_agent import process_receipt_image, process_document, process_image


async def save_file(file_content: bytes, filename: str, business_id: str, user_id: str) -> str:
    """
    Save uploaded file and return URL/path.
    
    Args:
        file_content: File bytes
        filename: Original filename
        business_id: Business ID
        user_id: User ID
        
    Returns:
        File URL or path
    """
    import aiofiles
    
    # Create directory structure
    upload_dir = f"uploads/{business_id}/{user_id}"
    os.makedirs(upload_dir, exist_ok=True)
    
    # Generate unique filename
    file_ext = os.path.splitext(filename)[1]
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(upload_dir, unique_filename)
    
    # Save file asynchronously
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(file_content)
    
    # Return file path (in production, upload to cloud storage and return URL)
    # For now, return URL that can be accessed via static file serving
    # In production, replace with actual cloud storage URL
    base_url = os.getenv("BASE_URL", "http://localhost:8000")
    return f"{base_url}/uploads/{business_id}/{user_id}/{unique_filename}"


async def process_uploaded_files(
    files: List[UploadFile],
    business_id: str,
    user_id: str,
    expected_product: Optional[str] = None,
    expected_amount: Optional[float] = None
) -> List[Dict[str, Any]]:
    """
    Process uploaded files - first with file_processor, then media_processing_agent if needed.
    
    Args:
        files: List of uploaded files
        business_id: Business ID
        user_id: User ID
        expected_product: Expected product name (for receipts)
        expected_amount: Expected amount (for receipts)
        
    Returns:
        List of processed file results
    """
    processed_files = []
    
    for file in files:
        # Read file content
        file_content = await file.read()
        # Reset file pointer for potential reuse
        await file.seek(0)
        content_type = file.content_type or "application/octet-stream"
        
        # First-line parsing with file_processor
        parse_result = await process_file(file_content, file.filename, content_type)
        
        # Save file
        file_url = await save_file(file_content, file.filename, business_id, user_id)
        
        result = {
            "filename": file.filename,
            "file_url": file_url,
            "content_type": content_type,
            "initial_parse": parse_result
        }
        
        # If poorly parsed or image/PDF, use media_processing_agent
        if (parse_result.get("poorly_parsed") or 
            not parse_result.get("success") or
            content_type.startswith("image/") or
            content_type == "application/pdf"):
            
            try:
                if content_type.startswith("image/"):
                    if expected_product or expected_amount:
                        # Receipt processing
                        media_result = await process_receipt_image(
                            file_url,
                            expected_product,
                            expected_amount
                        )
                    else:
                        # General image processing
                        media_result = await process_image(file_url, task="general")
                    result["media_processing"] = media_result
                    result["extracted_content"] = media_result.get("extracted_data") or media_result.get("analysis")
                elif content_type == "application/pdf":
                    media_result = await process_document(file_url, task="extract_text")
                    result["media_processing"] = media_result
                    result["extracted_content"] = media_result.get("content")
            except Exception as e:
                result["media_processing_error"] = str(e)
                result["extracted_content"] = parse_result.get("content", "")
        else:
            # Use initial parse result
            result["extracted_content"] = parse_result.get("content", "")
        
        processed_files.append(result)
    
    return processed_files
