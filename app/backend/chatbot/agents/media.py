"""Media processing agent — analyzes images and documents (receipts, product photos, etc.)."""

from typing import Any, Dict, Optional

from pydantic_ai import Agent, DocumentUrl, ImageUrl

from backend.config import MODEL_NAME

media_processing_agent = Agent(
    model=MODEL_NAME,
    deps_type=str,
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
)


async def process_image(
    image_url: str,
    task: str = "general",
) -> Dict[str, Any]:
    """Process an image for the given task type (receipt, product, general)."""
    prompt = f"""Analyze this image for: {task}

Image URL: {image_url}

Extract relevant information."""

    result = await media_processing_agent.run(
        [prompt, ImageUrl(url=image_url)],
    )

    return {"task": task, "analysis": result.output, "image_url": image_url}


async def process_document(
    document_url: str,
    task: str = "extract_text",
) -> Dict[str, Any]:
    """Process a document for the given task type."""
    prompt = f"""Process this document for: {task}

Document URL: {document_url}

Extract relevant information."""

    result = await media_processing_agent.run(
        [prompt, DocumentUrl(url=document_url)]
    )

    return {"task": task, "content": result.output, "document_url": document_url}


async def process_receipt_image(
    image_url: str,
    expected_product: Optional[str] = None,
    expected_amount: Optional[float] = None,
) -> Dict[str, Any]:
    """Process a receipt image for payment verification."""
    prompt = f"""Extract payment information from this receipt image.

Expected Product: {expected_product or 'Not specified'}
Expected Amount: {expected_amount or 'Not specified'}

Extract: amount paid, product name, transaction reference, bank details, date."""

    result = await media_processing_agent.run(
        [prompt, ImageUrl(url=image_url)]
    )

    return {"type": "receipt", "extracted_data": result.output, "image_url": image_url}
