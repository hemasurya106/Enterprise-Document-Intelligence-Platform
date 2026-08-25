"""
Pydantic models for authentication.

These are *runtime* models passed between the JWT middleware, auth router,
and route handlers.  They are NOT database models — MongoDB stores user
documents directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class AuthUser(BaseModel):
    """
    Authenticated user extracted from a verified JWT.

    Fields come directly from the JWT claims + optional DB lookup.
    """

    id: str = Field(..., description="MongoDB user _id (the 'sub' JWT claim)")
    email: str = Field(..., description="User's email address")
    full_name: Optional[str] = Field(
        default=None, description="Display name"
    )
    avatar_url: Optional[str] = Field(
        default=None, description="Profile picture URL"
    )


class UserProfile(BaseModel):
    """
    Full user profile from MongoDB — returned by GET /api/v1/auth/me.
    """

    id: str
    email: str
    full_name: Optional[str] = None
    created_at: datetime


# ── Request / Response schemas ────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr = Field(..., description="Email address")
    password: str = Field(..., min_length=8, description="Password (min 8 chars)")
    full_name: Optional[str] = Field(default=None, description="Display name")

    class Config:
        json_schema_extra = {
            "example": {
                "email": "jane@example.com",
                "password": "SecurePass1!",
                "full_name": "Jane Doe",
            }
        }


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="Email address")
    password: str = Field(..., description="Password")

    class Config:
        json_schema_extra = {
            "example": {
                "email": "jane@example.com",
                "password": "SecurePass1!",
            }
        }


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer")
