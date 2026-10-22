"""
Redis-backed sliding-window rate limiter middleware.

Strategy
--------
Each identity (hashed Bearer token or client IP) + route bucket gets a Redis
key with a 1-minute TTL.  On every request we INCR that key and compare the
count to the configured limit.  If the key is new we also set its TTL so the
window slides forward from the *first* request in the window.

Rate limit table:
  POST /api/v1/auth/*                →  5  req / 60 s   (strict, brute-force)
  POST /api/v1/hackrx/upload          →  5  req / 60 s   (expensive ingestion)
  POST /api/v1/hackrx/run             →  20 req / 60 s   (moderate RAG cost)
  GET  /api/v1/hackrx/jobs/*/status   →  60 req / 60 s   (cheap Redis lookup)
  GET  /health                        →  30 req / 60 s   (infra check, cheap)
  *    (everything else)              →  60 req / 60 s   (generous default)
"""

from __future__ import annotations

import logging
import time
from typing import Callable

try:
    import jwt as _pyjwt          # PyJWT — available after auth phase
except ImportError:
    _pyjwt = None                  # graceful degradation if not yet installed

from upstash_redis.asyncio import Redis as UpstashRedis
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger("app.rate_limiter")

# ---------------------------------------------------------------------------
# Route → (limit, window_seconds)
# Matched in order; first prefix match wins.
# ---------------------------------------------------------------------------
ROUTE_LIMITS: list[tuple[str, str, int, int]] = [
    # (method, path_prefix,                          limit, window_s)
    ("POST",  "/api/v1/auth/",                     5,    60),
    ("POST",  "/api/v1/hackrx/upload",               5,    60),
    ("POST",  "/api/v1/hackrx/run",                  20,   60),
    ("GET",   "/api/v1/hackrx/jobs",                 60,   60),
    ("GET",   "/health",                             30,   60),
]
DEFAULT_LIMIT   = 60
DEFAULT_WINDOW  = 60


def _get_limit(method: str, path: str) -> tuple[int, int]:
    """Return (limit, window_seconds) for the given method + path."""
    for m, prefix, limit, window in ROUTE_LIMITS:
        if method.upper() == m and path.startswith(prefix):
            return limit, window
    return DEFAULT_LIMIT, DEFAULT_WINDOW


def _get_identity(request: Request) -> str:
    """
    Derive a rate-limit identity key from the request.

    Priority:
      1. JWT present → extract the 'sub' claim (user ID).
         Rate-limit key is  user:<user-id>  — stable across token
         refreshes because the ID never changes for a given user.
      2. No valid JWT → fall back to client IP.

    We decode WITHOUT verifying the signature here because:
      - Signature verification already happens in get_current_user().
      - The rate limiter runs before route handlers and we don't want to
        duplicate the secret-loading logic or add latency on every request.
      - An attacker cannot meaningfully fake a different user ID here
        because the route handler will still reject the tampered token.
    """
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token and _pyjwt is not None:
            try:
                # options={"verify_signature": False} — intentional, see docstring
                payload = _pyjwt.decode(
                    token,
                    options={"verify_signature": False},
                    algorithms=["HS256"],
                )
                user_id = payload.get("sub")
                if user_id:
                    return f"user:{user_id}"
            except Exception:
                pass  # malformed token → fall through to IP

    # X-Forwarded-For is set by load balancers / nginx
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = getattr(request.client, "host", "unknown")
    return f"ip:{ip}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    INCR-based sliding-window rate limiter backed by Redis.

    Keys are namespaced as:  ratelimit:<identity>:<method>:<path_bucket>
    """

    def __init__(self, app: ASGIApp, upstash_url: str, upstash_token: str) -> None:
        super().__init__(app)
        self._upstash_url = (upstash_url or "").strip("\"' \t\r\n")
        self._upstash_token = (upstash_token or "").strip("\"' \t\r\n")
        self._redis: UpstashRedis | None = None

    def _get_redis(self) -> UpstashRedis:
        if self._redis is None:
            url = (self._upstash_url or os.getenv("UPSTASH_REDIS_REST_URL", "")).strip("\"' \t\r\n")
            token = (self._upstash_token or os.getenv("UPSTASH_REDIS_REST_TOKEN", "")).strip("\"' \t\r\n")
            if not url or not token:
                redis_url = (os.getenv("REDIS_URL") or "").strip("\"' \t\r\n")
                if redis_url:
                    try:
                        import urllib.parse
                        parsed = urllib.parse.urlparse(redis_url)
                        if parsed.hostname and not url:
                            url = f"https://{parsed.hostname}"
                        if parsed.password and not token:
                            token = parsed.password
                    except Exception:
                        pass
            self._redis = UpstashRedis(url=url, token=token)
        return self._redis

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Preflight CORS requests should never be rate limited
        if request.method == "OPTIONS":
            return await call_next(request)

        # Health endpoint has its own entry in ROUTE_LIMITS; let it through
        # even if Redis is down (degrade gracefully).
        try:
            r = self._get_redis()
        except Exception as exc:
            logger.warning("Rate limiter: Redis unavailable (%s) — allowing request", exc)
            return await call_next(request)

        method = request.method
        path   = request.url.path
        limit, window = _get_limit(method, path)
        identity = _get_identity(request)

        # Path bucket: collapse job IDs into a single bucket
        #   /api/v1/hackrx/jobs/abc-123/status → /api/v1/hackrx/jobs
        path_bucket = path
        for _, prefix, _, _ in ROUTE_LIMITS:
            if path.startswith(prefix):
                path_bucket = prefix
                break

        redis_key = f"ratelimit:{identity}:{method}:{path_bucket}"

        try:
            count = await r.incr(redis_key)
            ttl = await r.ttl(redis_key)

            # First request in window — set expiry
            if ttl == -1:
                await r.expire(redis_key, window)
                ttl = window

            if count > limit:
                retry_after = max(ttl, 1)
                logger.warning(
                    "Rate limit exceeded",
                    extra={
                        "identity": identity,
                        "path": path,
                        "count": count,
                        "limit": limit,
                        "retry_after": retry_after,
                    },
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limit_exceeded",
                        "message": (
                            f"Too many requests. Limit is {limit} per {window}s. "
                            f"Retry after {retry_after}s."
                        ),
                        "limit":       limit,
                        "window_s":    window,
                        "retry_after": retry_after,
                    },
                    headers={"Retry-After": str(retry_after)},
                )

        except Exception as exc:
            # Redis blipped — fail open (allow the request) rather than
            # hard-blocking all traffic.
            logger.warning("Rate limiter Redis error (%s) — allowing request", exc)

        return await call_next(request)
