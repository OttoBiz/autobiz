"""Cloudflare R2 / S3-compatible object storage for inbound media.

WhatsApp's media URLs are bearer-auth gated, so the model can't fetch them
directly. We download bytes once on webhook receipt and re-host them on R2 —
either at a public custom-domain URL or via a short-lived presigned URL —
so the agent can reference them via `pydantic_ai.ImageUrl` / `DocumentUrl`.

`is_configured()` lets the webhook fall back to inline base64 when R2 isn't
wired up (local dev, tests).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from backend import config as cfg

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(
        cfg.R2_ENDPOINT_URL
        and cfg.R2_ACCESS_KEY_ID
        and cfg.R2_SECRET_ACCESS_KEY
        and cfg.R2_BUCKET
    )


@lru_cache(maxsize=1)
def _client():
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "s3",
        endpoint_url=cfg.R2_ENDPOINT_URL,
        aws_access_key_id=cfg.R2_ACCESS_KEY_ID,
        aws_secret_access_key=cfg.R2_SECRET_ACCESS_KEY,
        # R2 ignores the region but boto3 requires one set; "auto" matches
        # Cloudflare's documented value.
        region_name="auto",
        config=BotoConfig(signature_version="s3v4"),
    )


def upload_bytes(data: bytes, key: str, content_type: str) -> Optional[str]:
    """Upload `data` to the configured R2 bucket and return a fetchable URL.

    Returns None on configuration or transport errors so the caller can fall
    back to inline base64 instead of dropping the inbound entirely.
    """
    if not is_configured():
        return None
    try:
        client = _client()
        client.put_object(
            Bucket=cfg.R2_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        if cfg.R2_PUBLIC_BASE_URL:
            base = cfg.R2_PUBLIC_BASE_URL.rstrip("/")
            return f"{base}/{key}"
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": cfg.R2_BUCKET, "Key": key},
            ExpiresIn=cfg.R2_PRESIGN_TTL,
        )
    except Exception as exc:
        logger.error("R2 upload failed key=%s err=%s", key, exc)
        return None
