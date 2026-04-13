"""
Upload pipeline: S3 only → media_processing_agent (structured output) → DB → batch for chat layer.
No local disk persistence; no PIL/file_processor in this path.
"""
from __future__ import annotations

import asyncio
import os
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


def _require_s3_url(content: bytes, key: str) -> str:
    url = _upload_s3_sync(content, key)
    if not url:
        raise RuntimeError(
            "File uploads require S3: set SAVE_UPLOADS_TO_S3=true, AWS_S3_BUCKET, "
            "AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_REGION; install boto3."
        )
    return url


async def _process_single_file(
    file: UploadFile,
    business_id: str,
    user_id: str,
) -> Dict[str, Any]:
    raw_name = file.filename or "upload"
    file_content = await file.read()
    await file.seek(0)
    content_type = file.content_type or "application/octet-stream"

    public_url = await asyncio.to_thread(
        _require_s3_url,
        file_content,
        _s3_key(business_id, user_id, raw_name),
    )

    structured: ProcessedUploadOutput = await analyze_upload_for_conversation(
        public_url,
        content_type,
        filename=raw_name,
    )

    kind = structured.file_content_type

    text_for_db = (structured.extracted_content or "").strip()
    desc = (structured.description or raw_name).strip()

    file_id = await insert_conversation_uploaded_file(
        user_id,
        business_id,
        file_url=public_url,
        file_content_type=kind,
        description=desc,
        text_content=text_for_db,
    )

    uploaded_at = datetime.now(timezone.utc).isoformat()
    receipt_payload = (
        structured.receipt.model_dump() if structured.receipt is not None else None
    )

    return {
        "filename": raw_name,
        "file_id": file_id,
        "file_url": public_url,
        "mime_type": content_type,
        "file_content_type": kind,
        "description": desc,
        "extracted_content": text_for_db,
        "receipt": receipt_payload,
        # "structured": structured.model_dump(),
        "product_attributes": dict(structured.product_attributes or {}),
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
                "description": (it["description"] or "")[:100],
                "uploaded_at": it["uploaded_at"],
            }
        )
        if it["file_content_type"] == UploadKind.receipt:
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
