"""
Media Processing Agent - Handles images and documents
Used as a tool for payment verification, product enquiry, etc.
"""
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext, ImageUrl, DocumentUrl, BinaryContent
from .base_agent import BaseAgent
import httpx


class MediaProcessingDeps(BaseModel):
    """Dependencies for media processing agent"""
    business_id: Optional[str] = None
    api_key: Optional[str] = None


# Initialize media processing agent
media_processing_agent_base = BaseAgent(
    system_prompt="""You are a media processing agent.

**YOUR JOB**
- Process images and documents uploaded by users
- Extract relevant information from images (receipts, product photos, etc.)
- Extract text and data from documents (PDFs, etc.)
- Provide structured information for other agents

**CAPABILITIES**
- Image analysis (receipts, product photos, IDs)
- Document text extraction
- Data extraction and structuring""",
    deps_type=MediaProcessingDeps
)

media_processing_agent = media_processing_agent_base.agent


async def process_image(
    image_url: str,
    task: str = "general",
    business_id: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Process an image.
    
    Args:
        image_url: URL of the image
        task: Task type (receipt, product, general)
        business_id: Business ID if relevant
        api_key: Optional API key
        
    Returns:
        Processed image information
    """
    deps = MediaProcessingDeps(business_id=business_id, api_key=api_key)
    
    prompt = f"""Analyze this image for: {task}

Image URL: {image_url}

Extract relevant information."""
    
    result = await media_processing_agent.run(
        [prompt, ImageUrl(url=image_url)],
        deps=deps
    )
    
    return {
        "task": task,
        "analysis": result.output,
        "image_url": image_url
    }


async def process_document(
    document_url: str,
    task: str = "extract_text",
    business_id: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Process a document.
    
    Args:
        document_url: URL of the document
        task: Task type
        business_id: Business ID if relevant
        api_key: Optional API key
        
    Returns:
        Processed document information
    """
    deps = MediaProcessingDeps(business_id=business_id, api_key=api_key)
    
    prompt = f"""Process this document for: {task}

Document URL: {document_url}

Extract relevant information."""
    
    result = await media_processing_agent.run(
        [prompt, DocumentUrl(url=document_url)],
        deps=deps
    )
    
    return {
        "task": task,
        "content": result.output,
        "document_url": document_url
    }


async def process_receipt_image(
    image_url: str,
    expected_product: Optional[str] = None,
    expected_amount: Optional[float] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Process receipt image for payment verification"""
    deps = MediaProcessingDeps(api_key=api_key)
    
    prompt = f"""Extract payment information from this receipt image.

Expected Product: {expected_product or 'Not specified'}
Expected Amount: {expected_amount or 'Not specified'}

Extract: amount paid, product name, transaction reference, bank details, date."""
    
    result = await media_processing_agent.run(
        [prompt, ImageUrl(url=image_url)],
        deps=deps
    )
    
    return {
        "type": "receipt",
        "extracted_data": result.output,
        "image_url": image_url
    }

