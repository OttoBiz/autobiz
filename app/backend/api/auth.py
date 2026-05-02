"""
Better-auth JWT verification dependency.

Contract:
    - Tokens are minted by better-auth's `/api/auth/token` endpoint.
    - JWKS is published at `BETTER_AUTH_JWKS_URL` and the issuer claim must
      match `BETTER_AUTH_ISSUER`.
    - Audience is the constant ``ottobiz-backend``.
    - `PyJWKClient` caches signing keys in-process and transparently refetches
      JWKS when an unknown ``kid`` is encountered, so key rotation requires no
      restart or manual cache invalidation.

Errors are returned in the standard API envelope:
    ``{"error": {"code": "unauthenticated"}}``
with HTTP 401. Failures are logged at WARNING level without leaking the token.
"""

import os
from functools import lru_cache
from uuid import UUID

import jwt
from jwt import PyJWKClient
from fastapi import Header, HTTPException, status
from pydantic import BaseModel

from backend.logging_config import get_logger

logger = get_logger(__name__)

AUDIENCE = "ottobiz-backend"

_UNAUTH_DETAIL = {"error": {"code": "unauthenticated"}}


@lru_cache(maxsize=1)
def _settings() -> tuple[str, str]:
    """Read auth env vars lazily so module import does not require them."""
    return os.environ["BETTER_AUTH_JWKS_URL"], os.environ["BETTER_AUTH_ISSUER"]


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    jwks_url, _ = _settings()
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=600)


class SessionContext(BaseModel):
    user_id: UUID
    business_id: UUID


def require_session(authorization: str = Header(...)) -> SessionContext:
    if not authorization.startswith("Bearer "):
        logger.warning("auth failed: missing bearer prefix")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _UNAUTH_DETAIL)

    token = authorization.removeprefix("Bearer ").strip()
    _, issuer = _settings()

    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token).key
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["EdDSA", "RS256", "ES256"],
            issuer=issuer,
            audience=AUDIENCE,
            leeway=30,
        )
    except jwt.PyJWTError as exc:
        logger.warning("auth failed: invalid token (%s)", exc.__class__.__name__)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _UNAUTH_DETAIL)

    if not payload.get("business_id"):
        logger.warning("auth failed: token missing business_id claim")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _UNAUTH_DETAIL)

    return SessionContext(
        user_id=payload["sub"],
        business_id=payload["business_id"],
    )
