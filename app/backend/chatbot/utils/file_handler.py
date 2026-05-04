"""
Upload pipeline: S3 (when configured) or inline data URL → media_processing_agent → DB → batch for chat.
No local disk persistence; no PIL/file_processor in this path.
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import UploadFile

from backend.chatbot.agents.media_processing_agent import (
    ProcessedUploadOutput,
    UploadKind,
    analyze_upload_for_conversation,
)
from backend.config import (
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    AWS_S3_BUCKET,
    AWS_S3_REGION,
    SAVE_UPLOADS_TO_S3,
)
from backend.db.db_utils import insert_conversation_uploaded_file


def _s3_key(business_id: str, user_id: str, filename: str) -> str:
    ext = os.path.splitext(filename)[1] or ".bin"
    return f"uploads/{business_id}/{user_id}/{uuid.uuid4()}{ext}"


def _upload_s3_sync(content: bytes, key: str) -> Optional[str]:
    if not (
        SAVE_UPLOADS_TO_S3
        and AWS_S3_BUCKET
        and AWS_ACCESS_KEY_ID
        and AWS_SECRET_ACCESS_KEY
    ):
        return None
    try:
        import boto3  # type: ignore
    except ImportError:
        return None
    try:
        client = boto3.client(
            "s3",
            region_name=AWS_S3_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )
        client.put_object(Bucket=AWS_S3_BUCKET, Key=key, Body=content)
        return f"https://{AWS_S3_BUCKET}.s3.{AWS_S3_REGION}.amazonaws.com/{key}"
    except Exception:
        return None


def _s3_configured() -> bool:
    return bool(
        SAVE_UPLOADS_TO_S3
        and AWS_S3_BUCKET
        and AWS_ACCESS_KEY_ID
        and AWS_SECRET_ACCESS_KEY
    )


def _heuristic_looks_like_bank_receipt(extracted: str, description: str) -> bool:
    """If the vision model labeled document as *others* but text clearly describes a transfer/bank receipt."""
    blob = f"{extracted or ''} {description or ''}".lower()
    if len(blob) < 16:
        return False
    bankish = any(
        w in blob
        for w in (
            "transfer",
            "gtco",
            "gtbank",
            "providus",
            "naira",
            "beneficiar",
            "receipt",
            "debit",
            "credit",
            "reference",
        )
    ) or "bank" in blob
    moneyish = "₦" in blob or "ngn" in blob or re.search(
        r"\d{1,3}(?:,\d{3})*(?:\.\d{1,2})", blob
    ) is not None
    return bool(bankish and (moneyish or re.search(r"\b\d{8,12}\b", blob)))


def _inline_data_url_for_model(file_content: bytes, content_type: str) -> str:
    """Public URL the media agent can use when S3 is off (e.g. local Docker). Capped for API limits."""
    if len(file_content) > 10_485_760:
        raise RuntimeError(
            "File exceeds 10 MB inline limit. Configure S3 (SAVE_UPLOADS_TO_S3 + bucket/credentials) for larger files."
        )
    b64 = base64.b64encode(file_content).decode("ascii")
    ct = (content_type or "application/octet-stream").split(";")[0].strip() or "application/octet-stream"
    return f"data:{ct};base64,{b64}"


async def _process_single_file(
    file: UploadFile,
    business_id: str,
    user_id: str,
) -> Dict[str, Any]:
    raw_name = file.filename or "upload"
    file_content = await file.read()
    await file.seek(0)
    content_type = file.content_type or "application/octet-stream"
    key = _s3_key(business_id, user_id, raw_name)
    s3_url = await asyncio.to_thread(_upload_s3_sync, file_content, key) if _s3_configured() else None
    if s3_url:
        public_url = s3_url
        file_url_for_db: Optional[str] = s3_url
    else:
        public_url = _inline_data_url_for_model(file_content, content_type)
        file_url_for_db = None  # do not store huge data: URLs in DB

    structured: ProcessedUploadOutput = await analyze_upload_for_conversation(
        public_url,
        content_type,
        filename=raw_name,
    )

    kind = structured.file_content_type

    ex = structured.extracted_content
    if ex is None:
        text_for_db = ""
    elif isinstance(ex, str):
        text_for_db = ex.strip()
    else:
        text_for_db = (
            ex.model_dump_json() if hasattr(ex, "model_dump_json") else str(ex)
        ).strip()
    desc = (structured.description or raw_name).strip()

    kind_str = kind.value if hasattr(kind, "value") else str(kind)
    if (kind_str or "").lower() != UploadKind.receipt.value and _heuristic_looks_like_bank_receipt(
        text_for_db, desc
    ):
        kind_str = UploadKind.receipt.value
    file_id = await insert_conversation_uploaded_file(
        user_id,
        business_id,
        file_url=file_url_for_db,
        file_content_type=kind_str,
        description=desc,
        text_content=text_for_db,
    )

    uploaded_at = datetime.now(timezone.utc).isoformat()
    _ec = structured.extracted_content
    receipt_payload = (
        _ec.model_dump()
        if str(kind_str).lower() == UploadKind.receipt.value
        and _ec is not None
        and hasattr(_ec, "model_dump")
        else None
    )

    return {
        "filename": raw_name,
        "file_id": file_id,
        "file_url": file_url_for_db or public_url,
        # "mime_type": content_type,
        "file_content_type": kind_str,
        "description": desc,
        "extracted_content": text_for_db,
        "receipt": receipt_payload,
        # "structured": structured.model_dump(),
        "product_attributes": structured.product_attributes,
        "uploaded_at": uploaded_at,
    }


async def process_uploaded_files(
    files: List[UploadFile],
    business_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """
    Parallel S3 + media agent per file.

    Returns:
        items: full per-file dicts
        uploaded_file_refs: metadata for user_state.uploaded_files
        receipt_data: combined receipt text for payment_verification_agent (single str, or None)
        non_receipt_attachment_lines: prompt lines for product/others only (no receipt body)

    Note: every file's extracted_content is persisted to DB via insert_conversation_uploaded_file.
    Receipt text is isolated from non-receipt attachment lines to avoid confusing product/general agents.
    """
    if not files:
        return {
            "items": [],
            "uploaded_file_refs": [],
            "receipt_data": None,
            "non_receipt_attachment_lines": [],
        }

    tasks = [_process_single_file(f, business_id, user_id) for f in files]
    items: List[Dict[str, Any]] = list(await asyncio.gather(*tasks))

    uploaded_file_refs: List[Dict[str, Any]] = []
    receipt_parts: List[str] = []
    non_receipt_lines: List[str] = []

    for it in items:
        uploaded_file_refs.append(
            {
                "file_id": it["file_id"],
                "filename": it["filename"],
                "file_content_type": it["file_content_type"],
                "description": (it["description"] or ""),
                "uploaded_at": it["uploaded_at"],
            }
        )
        if str(it["file_content_type"]).lower() == UploadKind.receipt.value:
            rp = it.get("receipt")
            if rp is not None:
                receipt_parts.append(
                    rp if isinstance(rp, str) else str(rp)
                )
            else:
                tx = (it.get("extracted_content") or "").strip()
                if tx:
                    receipt_parts.append(tx)
        else:
            non_receipt_lines.append(
                f"- id={it['file_id']} name={it['filename']} type={it['file_content_type']}: "
                f"{(it.get('description') or '')}"
            )

    return {
        "items": items,
        "uploaded_file_refs": uploaded_file_refs,
        "receipt_data": "\n\n---\n\n".join(receipt_parts) if receipt_parts else None,
        "non_receipt_attachment_lines": non_receipt_lines,
    }
