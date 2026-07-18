"""
/health endpoint — active liveness check for Redis and Celery workers.

Returns 200 if all checks pass, 503 if any check fails.
This lets load balancers (ELB, nginx, GCP, etc.) route traffic away from
unhealthy instances automatically.

Response schema:
{
  "status":    "healthy" | "degraded",
  "checks": {
    "redis":           {"status": "ok"|"error", "latency_ms": 1.2, "detail": "..."},
    "celery_workers":  {"status": "ok"|"error", "workers": [...], "detail": "..."}
  },
  "timestamp": "2026-07-18T07:00:00.000Z"
}
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import redis as redis_lib
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.celery_app import get_celery_app

logger   = logging.getLogger("app.health")
router   = APIRouter(tags=["ops"])
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _check_redis() -> dict:
    start = time.perf_counter()
    try:
        r = redis_lib.from_url(
            REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        r.ping()
        latency_ms = round((time.perf_counter() - start) * 1_000, 2)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start) * 1_000, 2)
        logger.warning("Health: Redis check failed: %s", exc)
        return {"status": "error", "latency_ms": latency_ms, "detail": str(exc)}


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


@router.get("/health", summary="Liveness + dependency health check")
async def health() -> JSONResponse:
    """
    Active health check:
      - Pings Redis (same instance used by Celery broker/backend)
      - Pings live Celery workers via control channel
    Returns 200 if all healthy, 503 if anything is degraded.
    """
    redis_result  = _check_redis()
    celery_result = _check_celery()

    all_ok = (
        redis_result["status"]  == "ok"
        and celery_result["status"] == "ok"
    )

    body = {
        "status":    "healthy" if all_ok else "degraded",
        "checks": {
            "redis":          redis_result,
            "celery_workers": celery_result,
        },
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    }

    http_status = 200 if all_ok else 503
    if not all_ok:
        logger.warning("Health check degraded: %s", body["checks"])
    return JSONResponse(content=body, status_code=http_status)
