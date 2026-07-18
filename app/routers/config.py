"""
Public config endpoint — exposes only the two browser-safe Supabase keys.

This lets the static index.html pick up SUPABASE_URL and SUPABASE_ANON_KEY
at runtime without hardcoding them in the HTML file, so the same artifact
works in development and production without rebuilding.

NEVER expose SUPABASE_SERVICE_ROLE_KEY or SUPABASE_JWT_SECRET here.
"""

from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["config"])


@router.get("/api/v1/config", summary="Public browser configuration")
async def get_public_config() -> JSONResponse:
    """
    Returns the two Supabase keys that are safe to expose in a browser.
    All other secrets (service_role_key, jwt_secret) are server-only.
    """
    return JSONResponse(
        content={
            "supabase_url":      os.getenv("SUPABASE_URL", ""),
            "supabase_anon_key": os.getenv("SUPABASE_ANON_KEY", ""),
        }
    )
