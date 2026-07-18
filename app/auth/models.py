"""
Pydantic models for authentication context.

These are *runtime* models passed between the JWT middleware and route
handlers.  They are NOT database models — Supabase Auth manages the
canonical user record in auth.users; we only store a minimal profile
supplement in public.user_profiles.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AuthUser(BaseModel):
    """
    Authenticated user extracted from a verified Supabase JWT.

    Fields come directly from the JWT claims — no DB round-trip required
    to identify the user on every request.
    """

    id: str = Field(..., description="Supabase user UUID (the 'sub' JWT claim)")
    email: str = Field(..., description="User's email address")
    full_name: Optional[str] = Field(
        default=None, description="Display name from Google OAuth"
    )
    avatar_url: Optional[str] = Field(
        default=None, description="Profile picture URL from Google OAuth"
    )


class UserProfile(BaseModel):
    """
    Row from public.user_profiles — the minimal supplement we store.
    Supabase Auth already stores id, email, created_at in auth.users;
    we only add full_name, avatar_url here.
    """

    id: str
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime
