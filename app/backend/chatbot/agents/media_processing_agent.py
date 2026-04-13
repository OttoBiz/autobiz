"""
Media Processing Agent - Handles images and documents
Used as a tool for payment verification, product enquiry, etc.
"""
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field
from pydantic_ai import ImageUrl, DocumentUrl

from .base_agent import BaseAgent

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


class ReceiptExtract(BaseModel):
    date: str = ""
    time: str = ""
    amount: float = 0.0
    currency: str = ""
    currency_rate: float = 1.0


class UploadKind:
    """Constants for upload classification (string values match model output)."""

    receipt = "receipt"
    product = "product"
    others = "others"


class ProcessedUploadOutput(BaseModel):
    """Structured result from the upload analyzer (single source of truth per file)."""

    file_content_type: str = UploadKind.others
    description: str = Field(default="", description="Short human summary of the file")
    extracted_content: str = Field(
        default="",
        description="Full usable text: transcript, OCR merge, or key facts as prose",
    )
    receipt: Optional[ReceiptExtract] = Field(
        default=None,
        description="If type=receipt, structured fields; else null",
    )
    product_attributes: Dict[str, Any] = Field(
        default_factory=dict,
        description="If product image: e.g. color, brand, product_name",
    )


_upload_analyzer_base = BaseAgent(
    system_prompt="""You classify and extract from a customer upload (image or PDF).

Rules:
- file_content_type must be exactly: receipt | product | others
- receipt: bank/payment slip, transfer confirmation, invoice paid
- product: photo of an item, packaging, shelf label for shopping
- others: anything else
- Fill extracted_content with all text/details useful to downstream agents (OCR, visible text, key facts).
- For receipt: parse receipt object when possible; estimate currency_rate 1.0 if single currency.
- For product: put guesses in product_attributes (product_name, color, brand, category hints).
- Be conservative: if unsure between receipt and others, use others.""",
    output_type=ProcessedUploadOutput,
)

_upload_analyzer = _upload_analyzer_base.agent


async def analyze_upload_for_conversation(
    file_url: str,
    content_type: str,
    filename: str = "",
) -> ProcessedUploadOutput:
    """
    Classify and extract via media model only (no local OCR/PIL). Requires a URL the model can fetch (e.g. public S3).
    """
    meta = f"\n\nOriginal filename: {filename}\nMIME: {content_type}"
    if content_type.startswith("image/"):
        prompt = f"Analyze this customer upload (image).{meta}"
        result = await _upload_analyzer.run([prompt, ImageUrl(url=file_url)])
    elif content_type == "application/pdf" or content_type.startswith("text/"):
        prompt = f"Analyze this customer upload (document).{meta}"
        result = await _upload_analyzer.run([prompt, DocumentUrl(url=file_url)])
    else:
        prompt = (
            "Classify this upload from metadata only (URL may not be loadable as PDF in this channel).\n"
            f"URL: {file_url}{meta}\n"
            "Set file_content_type conservatively; extracted_content empty if unsure."
        )
        result = await _upload_analyzer.run(prompt)
    out = result.output
    if not isinstance(out, ProcessedUploadOutput):
        return ProcessedUploadOutput(
            file_content_type=UploadKind.others,
            description="parse_failed",
            extracted_content=str(out),
        )
    t = str(out.file_content_type or UploadKind.others).lower().strip()
    if t not in (UploadKind.receipt, UploadKind.product, UploadKind.others):
        t = UploadKind.others
    out.file_content_type = t
    return out


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

