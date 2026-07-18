"""
Supabase JWT verification + FastAPI dependency.

How Supabase JWTs work
----------------------
Supabase issues JWTs signed with HS256 using your project's JWT secret
(Settings → API → JWT Settings → JWT Secret).  The token payload includes:

  {
    "sub":   "<supabase-user-uuid>",
    "email": "user@example.com",
    "aud":   "authenticated",
    "role":  "authenticated",
    "exp":   <unix timestamp>,
    "user_metadata": {
        "full_name":  "Jane Doe",
        "avatar_url": "https://..."
    }
  }

We verify the signature, expiry, and audience locally using PyJWT —
no network call to Supabase on every request.

Usage
-----
    from app.auth.jwt import get_current_user, AuthUser

    @router.post("/protected")
    async def my_endpoint(user: AuthUser = Depends(get_current_user)):
        ...
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import jwt as pyjwt                           # PyJWT
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import AuthUser

logger = logging.getLogger("app.auth.jwt")

_JWT_SECRET: Optional[str] = None
_SUPABASE_URL: Optional[str] = None

# HTTPBearer extracts the token from  Authorization: Bearer <token>
# auto_error=False so we can return a cleaner 401 ourselves
_bearer = HTTPBearer(auto_error=False)


def _get_jwt_secret() -> str:
    global _JWT_SECRET
    if _JWT_SECRET is None:
        secret = os.getenv("SUPABASE_JWT_SECRET")
        if not secret:
            raise RuntimeError(
                "SUPABASE_JWT_SECRET is not set. "
                "Add it to your .env (Settings → API → JWT Secret)."
            )
        _JWT_SECRET = secret
    return _JWT_SECRET


def verify_supabase_jwt(token: str) -> dict:
    """
    Decode and verify a Supabase-issued JWT.

    Raises HTTPException(401) on:
      - missing / malformed token
      - bad signature
      - expired token
      - wrong audience

    Returns the decoded payload dict on success.
    """
    try:
        payload = pyjwt.decode(
            token,
            _get_jwt_secret(),
            algorithms=["HS256"],
            audience="authenticated",   # Supabase sets aud="authenticated"
            options={"require": ["sub", "exp", "aud"]},
        )
        return payload
    except pyjwt.ExpiredSignatureError:
        logger.warning("JWT expired")
        raise HTTPException(status_code=401, detail="Token has expired")
    except pyjwt.InvalidAudienceError:
        logger.warning("JWT audience mismatch")
        raise HTTPException(status_code=401, detail="Invalid token audience")
    except pyjwt.InvalidSignatureError:
        logger.warning("JWT signature invalid")
        raise HTTPException(status_code=401, detail="Invalid token signature")
    except pyjwt.DecodeError as exc:
        logger.warning("JWT decode error: %s", exc)
        raise HTTPException(status_code=401, detail="Malformed token")
    except Exception as exc:
        logger.error("Unexpected JWT error: %s", exc, exc_info=True)
        raise HTTPException(status_code=401, detail="Token verification failed")


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AuthUser:
    """
    FastAPI dependency — extracts and verifies the Supabase JWT from the
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

    payload = verify_supabase_jwt(credentials.credentials)

    # Supabase puts Google profile data in user_metadata
    user_meta: dict = payload.get("user_metadata", {})

    user = AuthUser(
        id=payload["sub"],
        email=payload.get("email", user_meta.get("email", "")),
        full_name=user_meta.get("full_name") or user_meta.get("name"),
        avatar_url=user_meta.get("avatar_url") or user_meta.get("picture"),
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
