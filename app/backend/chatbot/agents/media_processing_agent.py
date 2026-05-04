"""
Media Processing Agent - Handles images and documents
Used as a tool for payment verification, product enquiry, etc.
"""
import base64
from typing import Any, Dict, Optional, Tuple, Union
from urllib.parse import unquote_to_bytes

from pydantic import BaseModel, Field
from pydantic_ai import BinaryContent, BinaryImage, DocumentUrl, ImageUrl

from .base_agent import BaseAgent
import enum

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
    # currency_rate: float = 1.0
    sender_account_details: Dict[str, Any] = Field(default_factory=dict)
    receiver_account_details: Dict[str, Any] = Field(default_factory=dict)


class UploadKind(enum.Enum):
    """Constants for upload classification (string values match model output)."""

    receipt = "receipt"
    product = "product"
    others = "others"

class ProductAttributes(BaseModel):
    product_name: Optional[str] = None
    attributes: Dict[str, Any]

class ProcessedUploadOutput(BaseModel):
    """Structured result from the upload analyzer (single source of truth per file)."""

    file_content_type: str = UploadKind.others
    description: str = Field(default="", description="very concise desc of the file content (one sentence)")
    extracted_content: Union[str, ReceiptExtract] = Field(
        default="",
        description="Full structured & usable text: transcript, OCR, or key facts as prose",
    )
    product_attributes: ProductAttributes = Field( None,
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
- PDF/slip showing **bank transfer, payment to account, or transfer confirmation** → **receipt** (not others). If genuinely not payment-related, use others.""",
    output_type=ProcessedUploadOutput,
)

_upload_analyzer = _upload_analyzer_base.agent


def _data_url_to_bytes_mime(data_url: str) -> Tuple[bytes, str]:
    """Parse a data: URL to raw bytes and declared MIME (no network fetch; SSRF-safe for pydantic_ai)."""
    if not data_url.startswith("data:"):
        raise ValueError("not a data URL")
    rest = data_url[5:]
    idx = rest.find(",")
    if idx < 0:
        raise ValueError("invalid data URL")
    meta, payload = rest[:idx], rest[idx + 1 :]
    if ";base64" in meta.lower():
        mime = (meta.split(";base64", 1)[0] or "application/octet-stream").strip() or "application/octet-stream"
        raw_b64 = "".join(payload.split())
        return base64.b64decode(raw_b64), mime
    mime = (meta.split(";", 1)[0] or "text/plain").strip() or "text/plain"
    return unquote_to_bytes(payload), mime


async def analyze_upload_for_conversation(
    file_url: str,
    content_type: str,
    filename: str = "",
) -> ProcessedUploadOutput:
    """
    Classify and extract via media model only (no local OCR/PIL). Uses http(s) URLs
    (e.g. S3) or inline data: URLs (decoded to BinaryImage/BinaryContent for the model).
    """
    meta = f"\n\nOriginal filename: {filename}\nMIME: {content_type}"
    use_data = file_url.strip().lower().startswith("data:")
    data_bytes: Optional[bytes] = None
    if use_data:
        data_bytes, _declared = _data_url_to_bytes_mime(file_url)

    if content_type.startswith("image/"):
        prompt = f"Analyze this customer upload (image).{meta}"
        if use_data and data_bytes is not None:
            part = BinaryImage(
                data=data_bytes,
                media_type=content_type,
                identifier=filename or None,
            )
        else:
            part = ImageUrl(url=file_url)
        result = await _upload_analyzer.run([prompt, part])
    elif content_type == "application/pdf" or content_type.startswith("text/"):
        prompt = f"Analyze this customer upload (document).{meta}"
        if use_data and data_bytes is not None:
            part = BinaryContent(
                data=data_bytes,
                media_type=content_type,
                identifier=filename or None,
            )
        else:
            part = DocumentUrl(url=file_url)
        result = await _upload_analyzer.run([prompt, part])
    else:
        url_for_prompt = file_url
        if use_data and data_bytes is not None:
            url_for_prompt = f"data:<inline, {len(data_bytes)} bytes>"
        prompt = (
            "Classify this upload from metadata only (URL may not be loadable as PDF in this channel).\n"
            f"URL: {url_for_prompt}{meta}\n"
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

