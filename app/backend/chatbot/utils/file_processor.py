"""
File Processor - First-line document parsing
Parses documents before media_processing_agent is used
"""
import re
from typing import Dict, Any, Optional
from io import BytesIO

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False

try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False


def is_poorly_parsed(text: str) -> bool:
    """
    Check if text is poorly parsed (repetitive sequences, unreadable characters).
    
    Args:
        text: Extracted text
        
    Returns:
        True if poorly parsed, False otherwise
    """
    if not text or len(text.strip()) < 10:
        return True
    
    # Check for repetitive sequences (more than 3 consecutive identical characters)
    if re.search(r'(.)\1{3,}', text):
        return True
    
    # Check for too many unreadable characters (more than 30% non-alphanumeric)
    readable_chars = len(re.findall(r'[a-zA-Z0-9\s]', text))
    if len(text) > 0 and readable_chars / len(text) < 0.7:
        return True
    
    # Check for too many special characters in a row
    if re.search(r'[^\w\s]{5,}', text):
        return True
    
    return False


async def parse_pdf(file_content: bytes, filename: str) -> Dict[str, Any]:
    """
    Parse PDF document.
    
    Args:
        file_content: PDF file bytes
        filename: Original filename
        
    Returns:
        Parsed content dictionary
    """
    try:
        full_text = ""
        
        # Try pdfplumber first (better for tables and structured data)
        if PDFPLUMBER_AVAILABLE:
            try:
                text_content = []
                with pdfplumber.open(BytesIO(file_content)) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            text_content.append(text)
                full_text = "\n".join(text_content)
            except Exception:
                pass
        
        # Fallback to PyPDF2 if pdfplumber failed or not available
        if (not full_text or is_poorly_parsed(full_text)) and PYPDF2_AVAILABLE:
            try:
                pdf_reader = PyPDF2.PdfReader(BytesIO(file_content))
                text_content = []
                for page in pdf_reader.pages:
                    text = page.extract_text()
                    if text:
                        text_content.append(text)
                full_text = "\n".join(text_content)
            except Exception:
                pass
        
        if not full_text:
            return {
                "success": False,
                "error": "Could not extract text from PDF",
                "type": "pdf",
                "filename": filename,
                "poorly_parsed": True
            }
        
        return {
            "success": True,
            "content": full_text,
            "type": "pdf",
            "filename": filename,
            "poorly_parsed": is_poorly_parsed(full_text)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "type": "pdf",
            "filename": filename,
            "poorly_parsed": True
        }


async def parse_image(file_content: bytes, filename: str) -> Dict[str, Any]:
    """
    Parse image file. Uses OCR (pytesseract) when available; falls back to AI if poor.
    """
    if not PIL_AVAILABLE:
        return {
            "success": False,
            "error": "PIL/Pillow not available",
            "type": "image",
            "filename": filename,
            "poorly_parsed": True,
        }

    try:
        image = Image.open(BytesIO(file_content))
        content = None
        if PYTESSERACT_AVAILABLE:
            try:
                content = pytesseract.image_to_string(image)
                content = (content or "").strip()
            except Exception:  # Tesseract not installed or OCR failed
                pass

        poorly_parsed = is_poorly_parsed(content) if content else True
        return {
            "success": bool(content),
            "content": content,
            "type": "image",
            "filename": filename,
            "format": image.format,
            "size": image.size,
            "mode": image.mode,
            "poorly_parsed": poorly_parsed,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "type": "image",
            "filename": filename,
            "poorly_parsed": True,
        }


async def process_file(file_content: bytes, filename: str, content_type: str) -> Dict[str, Any]:
    """
    Process uploaded file - first-line parsing.
    
    Args:
        file_content: File bytes
        filename: Original filename
        content_type: MIME type
        
    Returns:
        Parsed content dictionary with success status and parsing quality
    """
    if content_type.startswith("image/"):
        return await parse_image(file_content, filename)
    elif content_type == "application/pdf":
        return await parse_pdf(file_content, filename)
    elif content_type.startswith("text/"):
        try:
            text = file_content.decode("utf-8")
            return {
                "success": True,
                "content": text,
                "type": "text",
                "filename": filename,
                "poorly_parsed": is_poorly_parsed(text)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "type": "text",
                "filename": filename
            }
    else:
        return {
            "success": False,
            "error": f"Unsupported file type: {content_type}",
            "type": "unknown",
            "filename": filename
        }
