"""
Public config endpoint — returns non-sensitive runtime configuration.

Previously exposed Supabase keys; now auth is self-managed so this
endpoint is minimal.  Kept for forward-compatibility (e.g. feature flags).
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["config"])


@router.get("/api/v1/config", summary="Public runtime configuration")
async def get_public_config() -> JSONResponse:
    """
    Returns non-sensitive runtime config for the frontend.
    Auth is now self-managed (email/password + JWT), so no external
    provider keys are needed.
    """
    return JSONResponse(
        content={
            "auth_provider": "self-managed",
            "auth_endpoints": {
                "register": "/api/v1/auth/register",
                "login": "/api/v1/auth/login",
                "me": "/api/v1/auth/me",
            },
        }
    )
