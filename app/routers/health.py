"""
/health endpoint — active liveness check for Redis, Celery workers, and MongoDB.

Returns 200 if Redis + MongoDB are ok (Celery is informational only).
This lets load balancers (ELB, nginx, GCP, etc.) route traffic away from
unhealthy instances automatically.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from upstash_redis.asyncio import Redis as UpstashRedis
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.celery_app import get_celery_app

logger   = logging.getLogger("app.health")
router   = APIRouter(tags=["ops"])
UPSTASH_URL   = os.getenv("UPSTASH_REDIS_REST_URL", "")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

async def _check_redis() -> dict:
    start = time.perf_counter()
    url   = (os.getenv("UPSTASH_REDIS_REST_URL")   or UPSTASH_URL).strip("\"' \t\r\n")
    token = (os.getenv("UPSTASH_REDIS_REST_TOKEN") or UPSTASH_TOKEN).strip("\"' \t\r\n")
    redis_url = (os.getenv("REDIS_URL") or "").strip("\"' \t\r\n")

    if (not url or not token) and redis_url:
        try:
            import urllib.parse
            parsed = urllib.parse.urlparse(redis_url)
            if parsed.hostname and not url: url = f"https://{parsed.hostname}"
            if parsed.password and not token: token = parsed.password
        except Exception:
            pass

    if url and token:
        try:
            r = UpstashRedis(url=url, token=token)
            await r.get("health_check_ping")
            return {"status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 2)}
        except Exception as exc:
            logger.warning("Health: Upstash REST check failed (%s); trying fallback...", exc)

    if redis_url:
        try:
            import redis as redis_lib
            clean_url = redis_url.replace("CERT_REQUIRED", "required")
            loop = asyncio.get_event_loop()
            r = await loop.run_in_executor(None, lambda: redis_lib.from_url(clean_url, socket_timeout=2, socket_connect_timeout=2))
            await loop.run_in_executor(None, r.ping)
            return {"status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 2)}
        except Exception as exc:
            return {"status": "error", "latency_ms": round((time.perf_counter() - start) * 1000, 2), "detail": str(exc)}

    return {"status": "error", "latency_ms": round((time.perf_counter() - start) * 1000, 2), "detail": "No credentials"}

def _check_celery_sync() -> dict:
    try:
        celery  = get_celery_app()
        inspect = celery.control.inspect(timeout=1)
        pong    = inspect.ping()
        if not pong: return {"status": "error", "workers": [], "detail": "No workers responded"}
        return {"status": "ok", "workers": list(pong.keys())}
    except Exception as exc:
        return {"status": "error", "workers": [], "detail": str(exc)}

async def _check_celery() -> dict:
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(loop.run_in_executor(None, _check_celery_sync), timeout=3.0)
    except asyncio.TimeoutError:
        return {"status": "error", "workers": [], "detail": "Timed out after 3s"}

def _check_mongodb() -> dict:
    start = time.perf_counter()
    try:
        from app.auth.mongodb_client import get_mongo_client, _get_collection
        if get_mongo_client() is None: _get_collection()
        get_mongo_client().admin.command("ping")
        return {"status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 2)}
    except Exception as exc:
        return {"status": "error", "latency_ms": round((time.perf_counter() - start) * 1000, 2), "detail": str(exc)}

@router.get("/health", summary="Liveness + dependency health check")
async def health() -> JSONResponse:
    loop = asyncio.get_event_loop()
    redis_result, celery_result, mongodb_result = await asyncio.gather(
        _check_redis(),
        _check_celery(),
        loop.run_in_executor(None, _check_mongodb),
    )

    # Celery is intentionally excluded — it starts separately from the web process.
    all_ok = (redis_result["status"] == "ok" and mongodb_result["status"] == "ok")

    body = {
        "status":    "healthy" if all_ok else "degraded",
        "checks":    {"redis": redis_result, "celery_workers": celery_result, "mongodb": mongodb_result},
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    }
    http_status = 200 if all_ok else 503
    if not all_ok: logger.warning("Health check degraded: %s", body["checks"])
    return JSONResponse(content=body, status_code=http_status)
