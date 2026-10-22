"""
Authentication endpoints — register, login, and profile retrieval.

All auth is self-managed:
  - Passwords are hashed with bcrypt and stored in MongoDB.
  - JWTs are signed by the backend with HS256 using JWT_SECRET.
  - No external auth provider required.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

from app.auth.jwt import create_access_token, get_current_user
from app.auth.models import (
    AuthUser,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserProfile,
)
from app.auth.mongodb_client import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    verify_password,
)

logger = logging.getLogger("app.auth.router")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest) -> TokenResponse:
    """
    Create a new user account and return a JWT.

    Returns 409 if the email is already registered.
    """
    try:
        user_doc = create_user(
            email=req.email,
            password=req.password,
            full_name=req.full_name,
        )
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="A user with this email already exists",
        )

    token = create_access_token(user_id=user_doc["_id"], email=user_doc["email"])
    logger.info(
        "User registered",
        extra={"user_id": user_doc["_id"], "email": user_doc["email"]},
    )
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest) -> TokenResponse:
    """
    Authenticate with email + password and return a JWT.

    Returns 401 on bad credentials (deliberately vague to avoid
    user-enumeration attacks).
    """
    user_doc = get_user_by_email(req.email)
    if user_doc is None or not verify_password(req.password, user_doc["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(user_id=user_doc["_id"], email=user_doc["email"])
    logger.info("User logged in", extra={"user_id": user_doc["_id"]})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserProfile)
async def get_me(user: AuthUser = Depends(get_current_user)) -> UserProfile:
    """
    Return the authenticated user's profile from MongoDB.
    """
    user_doc = get_user_by_id(user.id)
    if user_doc is None:
        raise HTTPException(status_code=404, detail="User not found")

    return UserProfile(
        id=user_doc["_id"],
        email=user_doc["email"],
        full_name=user_doc.get("full_name"),
        created_at=user_doc["created_at"],
    )
