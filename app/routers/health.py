"""
/health endpoint — active liveness check for Redis, Celery workers, and MongoDB.

Returns 200 if all checks pass, 503 if any check fails.
This lets load balancers (ELB, nginx, GCP, etc.) route traffic away from
unhealthy instances automatically.

Response schema:
{
  "status":    "healthy" | "degraded",
  "checks": {
    "redis":           {"status": "ok"|"error", "latency_ms": 1.2, "detail": "..."},
    "celery_workers":  {"status": "ok"|"error", "workers": [...], "detail": "..."},
    "mongodb":         {"status": "ok"|"error", "latency_ms": 1.2, "detail": "..."}
  },
  "timestamp": "2026-07-18T07:00:00.000Z"
}
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

from upstash_redis import Redis as UpstashRedis
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.celery_app import get_celery_app

logger   = logging.getLogger("app.health")
router   = APIRouter(tags=["ops"])
UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")


def _check_redis() -> dict:
    start = time.perf_counter()
    url = (os.getenv("UPSTASH_REDIS_REST_URL") or UPSTASH_URL).strip("\"' \t\r\n")
    token = (os.getenv("UPSTASH_REDIS_REST_TOKEN") or UPSTASH_TOKEN).strip("\"' \t\r\n")
    redis_url = (os.getenv("REDIS_URL") or "").strip("\"' \t\r\n")

    # If REST URL/token is missing, attempt to derive from REDIS_URL
    if (not url or not token) and redis_url:
        try:
            import urllib.parse
            parsed = urllib.parse.urlparse(redis_url)
            if parsed.hostname and not url:
                url = f"https://{parsed.hostname}"
            if parsed.password and not token:
                token = parsed.password
        except Exception:
            pass

    # 1. Try Upstash REST API check
    if url and token:
        try:
            r = UpstashRedis(url=url, token=token)
            r.get("health_check_ping")
            latency_ms = round((time.perf_counter() - start) * 1_000, 2)
            return {"status": "ok", "latency_ms": latency_ms}
        except Exception as exc:
            logger.warning("Health: Upstash REST check failed (%s); trying Redis TCP fallback...", exc)

    # 2. Resilient Fallback: Standard Redis TCP ping (same connection used by Celery)
    if redis_url:
        try:
            import redis as redis_lib
            clean_url = redis_url.replace("CERT_REQUIRED", "required")
            r = redis_lib.from_url(clean_url, socket_timeout=2, socket_connect_timeout=2)
            r.ping()
            latency_ms = round((time.perf_counter() - start) * 1_000, 2)
            return {"status": "ok", "latency_ms": latency_ms}
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start) * 1_000, 2)
            logger.warning("Health: Redis TCP fallback check failed: %s", exc)
            return {"status": "error", "latency_ms": latency_ms, "detail": str(exc)}

    latency_ms = round((time.perf_counter() - start) * 1_000, 2)
    return {"status": "error", "latency_ms": latency_ms, "detail": "No Redis credentials configured"}


def _check_celery() -> dict:
    """
    Ping all Celery workers with a 2-second timeout.
    Returns list of responding worker names.
    """
    try:
        celery = get_celery_app()
        inspect = celery.control.inspect(timeout=2)
        pong    = inspect.ping()  # dict: {worker_name: {"ok": "pong"}} or None
        if not pong:
            return {
                "status": "error",
                "workers": [],
                "detail": "No workers responded to ping within 2s",
            }
        workers = list(pong.keys())
        return {"status": "ok", "workers": workers}
    except Exception as exc:
        logger.warning("Health: Celery check failed: %s", exc)
        return {"status": "error", "workers": [], "detail": str(exc)}


def _check_mongodb() -> dict:
    """Ping MongoDB with a 2-second timeout."""
    start = time.perf_counter()
    try:
        from app.auth.mongodb_client import get_mongo_client

        client = get_mongo_client()
        if client is None:
            # MongoDB client hasn't been initialised yet (no auth requests made)
            # Try creating one for the health check
            from app.auth.mongodb_client import _get_collection
            _get_collection()  # triggers lazy init
            client = get_mongo_client()

        client.admin.command("ping")
        latency_ms = round((time.perf_counter() - start) * 1_000, 2)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start) * 1_000, 2)
        logger.warning("Health: MongoDB check failed: %s", exc)
        return {"status": "error", "latency_ms": latency_ms, "detail": str(exc)}


@router.get("/health", summary="Liveness + dependency health check")
async def health() -> JSONResponse:
    """
    Active health check:
      - Pings Redis (same instance used by Celery broker/backend)
      - Pings live Celery workers via control channel
      - Pings MongoDB (user store)
    Returns 200 if all healthy, 503 if anything is degraded.
    """
    redis_result   = _check_redis()
    celery_result  = _check_celery()
    mongodb_result = _check_mongodb()

    all_ok = (
        redis_result["status"]   == "ok"
        and celery_result["status"] == "ok"
        and mongodb_result["status"] == "ok"
    )

    body = {
        "status":    "healthy" if all_ok else "degraded",
        "checks": {
            "redis":          redis_result,
            "celery_workers": celery_result,
            "mongodb":        mongodb_result,
        },
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    }

    http_status = 200 if all_ok else 503
    if not all_ok:
        logger.warning("Health check degraded: %s", body["checks"])
    return JSONResponse(content=body, status_code=http_status)
