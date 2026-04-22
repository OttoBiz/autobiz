"""
Media Processing Agent - Handles images and documents
Used as a tool for payment verification, product enquiry, etc.
"""
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext, ImageUrl, DocumentUrl, BinaryContent
from .base_agent import BaseAgent
import httpx

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
    deps_type=str
)

media_processing_agent = media_processing_agent_base.agent


async def process_image(
    image_url: str ,
    task: str = "general",
) -> Dict[str, Any]:
    """
    Process an image.
    
    Args:
        image_url: URL of the image
        task: Task type (receipt, product, general)
        
    Returns:
        Processed image information
    """  
    
    prompt = f"""Analyze this image for: {task}

Image URL: {image_url}

Extract relevant information."""
    
    result = await media_processing_agent.run(
        [prompt, ImageUrl(url=image_url)],
    )
    
    return {
        "task": task,
        "analysis": result.output,
        "image_url": image_url
    }


async def process_document(
    document_url: str,
    task: str = "extract_text",
) -> Dict[str, Any]:
    """
    Process a document.
    
    Args:
        document_url: URL of the document
        task: Task type
        
    Returns:
        Processed document information
    """
    
    prompt = f"""Process this document for: {task}

Document URL: {document_url}

Extract relevant information."""
    
    result = await media_processing_agent.run(
        [prompt, DocumentUrl(url=document_url)]
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
) -> Dict[str, Any]:
    """Process receipt image for payment verification"""
    
    prompt = f"""Extract payment information from this receipt image.

Expected Product: {expected_product or 'Not specified'}
Expected Amount: {expected_amount or 'Not specified'}

Extract: amount paid, product name, transaction reference, bank details, date."""
    
    result = await media_processing_agent.run(
        [prompt, ImageUrl(url=image_url)]
    )
    
    return {
        "type": "receipt",
        "extracted_data": result.output,
        "image_url": image_url
    }

