"""
Supabase Python client — used for server-side DB writes only.

Why service role key?
---------------------
Row Level Security (RLS) on public.user_profiles is scoped to the calling
user's JWT (auth.uid() = id).  The backend doesn't send user JWTs to
Supabase — it uses the service role key to bypass RLS for the upsert.
The service role key is NEVER returned to the frontend.

The client is a lazy singleton so the connection is reused across requests.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from supabase import create_client, Client

from app.auth.models import AuthUser

logger = logging.getLogger("app.auth.supabase_client")

_client: Optional[Client] = None


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env"
            )
        _client = create_client(url, key)
    return _client


def upsert_user_profile(user: AuthUser) -> None:
    """
    Write the user's minimal profile to public.user_profiles on first login.

    Uses INSERT ... ON CONFLICT (id) DO NOTHING so:
      - First login  → row created
      - Repeat calls → no-op (idempotent, zero cost)
      - Manual edits → not overwritten

    Safe to call on every authenticated request because of the DO NOTHING.
    In practice, call it only on upload/run endpoints to avoid latency on
    every status poll.
    """
    try:
        client = _get_client()
        client.table("user_profiles").upsert(
            {
                "id":         user.id,
                "email":      user.email,
                "full_name":  user.full_name,
                "avatar_url": user.avatar_url,
            },
            on_conflict="id",           # match existing row by PK
            ignore_duplicates=True,     # DO NOTHING if already exists
        ).execute()
        logger.debug(
            "user_profiles upsert complete",
            extra={"user_id": user.id},
        )
    except Exception as exc:
        # Profile upsert failure must NOT block the main request
        logger.warning(
            "user_profiles upsert failed (non-fatal): %s",
            exc,
            extra={"user_id": user.id},
        )
