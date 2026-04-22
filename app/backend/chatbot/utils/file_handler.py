"""
File Handler - Handles file uploads and processing
"""
import asyncio
import os
import uuid
from typing import List, Dict, Any, Optional
from fastapi import UploadFile
from backend.chatbot.utils.file_processor import process_file
from backend.chatbot.agents.media import process_receipt_image, process_document, process_image


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


async def _process_single_file(
    file: UploadFile,
    business_id: str,
    user_id: str,
    expected_product: Optional[str],
    expected_amount: Optional[float],
) -> Dict[str, Any]:
    """Process a single file. Used for parallel execution."""
    file_content = await file.read()
    await file.seek(0)
    content_type = file.content_type or "application/octet-stream"

    parse_result = await process_file(file_content, file.filename, content_type)
    file_url = await save_file(file_content, file.filename, business_id, user_id)

    result: Dict[str, Any] = {
        "filename": file.filename,
        "file_url": file_url,
        "content_type": content_type,
        "initial_parse": parse_result,
    }

    use_ai = (
        parse_result.get("poorly_parsed")
        or not parse_result.get("success")
        or (content_type.startswith("image/") and not parse_result.get("content"))
    )
    if use_ai:
        try:
            if content_type.startswith("image/"):
                media_result = (
                    await process_receipt_image(file_url, expected_product, expected_amount)
                    if (expected_product or expected_amount)
                    else await process_image(file_url, task="general")
                )
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
        result["extracted_content"] = parse_result.get("content", "") or ""

    return result


async def process_uploaded_files(
    files: List[UploadFile],
    business_id: str,
    user_id: str,
    expected_product: Optional[str] = None,
    expected_amount: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Process uploaded files in parallel.
    """
    if not files:
        return []

    tasks = [
        _process_single_file(f, business_id, user_id, expected_product, expected_amount)
        for f in files
    ]
    return list(await asyncio.gather(*tasks))
