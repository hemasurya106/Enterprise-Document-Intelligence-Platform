"""
Self-managed JWT authentication — replaces Supabase JWT verification.

The backend signs its own JWTs with HS256 using ``JWT_SECRET``.
Tokens contain:
    {
        "sub":   "<mongodb-user-id>",
        "email": "user@example.com",
        "exp":   <unix timestamp>
    }

Usage
-----
    from app.auth.jwt import get_current_user, create_access_token
    from app.auth.models import AuthUser

    @router.post("/protected")
    async def my_endpoint(user: AuthUser = Depends(get_current_user)):
        ...
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt as pyjwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import AuthUser

logger = logging.getLogger("app.auth.jwt")

_JWT_SECRET: Optional[str] = None
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_HOURS = 24

# HTTPBearer extracts the token from  Authorization: Bearer <token>
# auto_error=False so we can return a cleaner 401 ourselves
_bearer = HTTPBearer(auto_error=False)


def _get_jwt_secret() -> str:
    global _JWT_SECRET
    if _JWT_SECRET is None:
        secret = (os.getenv("JWT_SECRET") or "").strip("\"' \t\r\n")
        if not secret:
            raise RuntimeError(
                "JWT_SECRET is not set. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
        _JWT_SECRET = secret
    return _JWT_SECRET


# ---------------------------------------------------------------------------
# Token creation (called by auth router on login/register)
# ---------------------------------------------------------------------------

def create_access_token(user_id: str, email: str) -> str:
    """
    Sign a new JWT with the user's ID and email.
    Token expires after ``_JWT_EXPIRY_HOURS`` hours.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now + timedelta(hours=_JWT_EXPIRY_HOURS),
    }
    token = pyjwt.encode(payload, _get_jwt_secret(), algorithm=_JWT_ALGORITHM)
    return token


# ---------------------------------------------------------------------------
# Token verification (called by get_current_user dependency)
# ---------------------------------------------------------------------------

def verify_jwt(token: str) -> dict:
    """
    Decode and verify a self-signed JWT.

    Raises HTTPException(401) on:
      - missing / malformed token
      - bad signature
      - expired token

    Returns the decoded payload dict on success.
    """
    try:
        payload = pyjwt.decode(
            token,
            _get_jwt_secret(),
            algorithms=[_JWT_ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
        return payload
    except pyjwt.ExpiredSignatureError:
        logger.warning("JWT expired")
        raise HTTPException(status_code=401, detail="Token has expired")
    except pyjwt.InvalidSignatureError:
        logger.warning("JWT signature invalid")
        raise HTTPException(status_code=401, detail="Invalid token signature")
    except pyjwt.DecodeError as exc:
        logger.warning("JWT decode error: %s", exc)
        raise HTTPException(status_code=401, detail="Malformed token")
    except Exception as exc:
        logger.error("Unexpected JWT error: %s", exc, exc_info=True)
        raise HTTPException(status_code=401, detail="Token verification failed")


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AuthUser:
    """
    FastAPI dependency — extracts and verifies the JWT from the
    Authorization: Bearer header, then returns a typed AuthUser.

    Inject with:  user: AuthUser = Depends(get_current_user)

    Returns 401 if:
      - No Authorization header present
      - Token is invalid / expired / tampered with
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_jwt(credentials.credentials)

    user = AuthUser(
        id=payload["sub"],
        email=payload.get("email", ""),
        full_name=None,      # not stored in JWT — fetch from DB if needed
        avatar_url=None,
    )

    logger.debug(
        "Authenticated request",
        extra={"user_id": user.id, "email": user.email},
    )
    return user


# Optional dependency that returns None for unauthenticated requests
# (for routes that are public but can optionally use auth context)
def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[AuthUser]:
    """
    Like get_current_user but returns None instead of raising 401.
    Use for routes that are public but can optionally use auth context.
    """
    if credentials is None:
        return None
    try:
        return get_current_user(credentials)
    except HTTPException:
        return None
