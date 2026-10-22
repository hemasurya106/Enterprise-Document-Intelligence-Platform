"""
Structured JSON request/response logging middleware.

Every request gets a UUID4 request_id that is:
  - stored in a contextvars.ContextVar so any logger inside the request
    handler can include it without being explicitly passed.
  - returned in the X-Request-ID response header so clients can correlate
    logs with their own tracing.

Log line shape (one JSON object per line):
{
  "ts":          "2026-07-18T07:00:00.123Z",
  "level":       "INFO",
  "logger":      "app.access",
  "request_id":  "550e8400-e29b-41d4-a716-446655440000",
  "method":      "POST",
  "path":        "/api/v1/hackrx/upload",
  "status_code": 200,
  "latency_ms":  142.7,
  "client_ip":   "1.2.3.4",
  "user_id":     null          # populated if Authorization: Bearer present
}
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# ---------------------------------------------------------------------------
# Context variable — available anywhere in the same async task
# ---------------------------------------------------------------------------
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """Return the current request_id (usable from any module in the request scope)."""
    return request_id_ctx.get()


# ---------------------------------------------------------------------------
# JSON formatter for the root logger
# ---------------------------------------------------------------------------
class _JsonFormatter(logging.Formatter):
    """Render every log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts":         self.formatTime(record, "%Y-%m-%dT%H:%M:%S.") + f"{record.msecs:03.0f}Z",
            "level":      record.levelname,
            "logger":     record.name,
            "request_id": request_id_ctx.get("-"),
            "message":    record.getMessage(),
        }
        # Merge any extra fields the caller passed via `extra={...}`
        skip = {
            "name", "msg", "args", "levelname", "levelno", "pathname",
            "filename", "module", "exc_info", "exc_text", "stack_info",
            "lineno", "funcName", "created", "msecs", "relativeCreated",
            "thread", "threadName", "processName", "process", "taskName",
            "message",
        }
        for k, v in record.__dict__.items():
            if k not in skip:
                payload[k] = v

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_json_logging(level: int = logging.INFO) -> None:
    """
    Call once at application startup (in main.py) to switch the root logger
    to JSON output.  Safe to call multiple times.
    """
    root = logging.getLogger()
    if any(isinstance(h, logging.StreamHandler) and isinstance(h.formatter, _JsonFormatter)
           for h in root.handlers):
        return  # already configured

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
_access_logger = logging.getLogger("app.access")


def _extract_user_id(request: Request) -> str | None:
    """
    Very lightweight: if there's a Bearer token, return its first 8 chars
    as a pseudonymised user_id for logging (not the full token).
    Replace with real JWT decode once auth is added.
    """
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return f"token:{token[:8]}…" if len(token) >= 8 else "token:short"
    return None


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Attach request_id to context, then log access after response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        req_id = str(uuid.uuid4())
        token  = request_id_ctx.set(req_id)

        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            latency_ms = (time.perf_counter() - start) * 1_000
            status = response.status_code if response is not None else 500

            forwarded = request.headers.get("X-Forwarded-For")
            client_ip = (
                forwarded.split(",")[0].strip()
                if forwarded
                else getattr(request.client, "host", "unknown")
            )

            _access_logger.info(
                "%s %s %s",
                request.method,
                request.url.path,
                status,
                extra={
                    "request_id": req_id,
                    "method":     request.method,
                    "path":       request.url.path,
                    "status_code": status,
                    "latency_ms": round(latency_ms, 2),
                    "client_ip":  client_ip,
                    "user_id":    _extract_user_id(request),
                },
            )

            # Propagate request-id to caller for distributed tracing
            if response is not None:
                response.headers["X-Request-ID"] = req_id

            request_id_ctx.reset(token)
