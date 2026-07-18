"""
Self-contained integration test for production hardening features.
No Docker / Redis / Celery required — uses fakeredis for rate limiter tests
and unittest.mock for health checks.

Run:  python3 test_hardening.py
"""
import asyncio
import json
import logging
import sys
import time
import threading
import types
import unittest
from unittest.mock import MagicMock, patch
from io import StringIO

# ─── colour helpers ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

passed = failed = 0

def ok(label):
    global passed
    passed += 1
    print(f"  {GREEN}✅  PASS{RESET}  {label}")

def fail(label, reason=""):
    global failed
    failed += 1
    print(f"  {RED}❌  FAIL{RESET}  {label}  {YELLOW}{reason}{RESET}")

def section(title):
    print(f"\n{BOLD}{'─'*60}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'─'*60}{RESET}")

# ══════════════════════════════════════════════════════════════════════════════
# 1. CIRCUIT BREAKER
# ══════════════════════════════════════════════════════════════════════════════
section("1. Gemini Circuit Breaker")

sys.path.insert(0, ".")
from app.utils.gemini_circuit_breaker import GeminiCircuitBreaker, _State

# --- state machine ---
def test_cb_starts_closed():
    cb = GeminiCircuitBreaker(failure_threshold=3, recovery_timeout_s=60, call_timeout_s=5)
    assert cb._state == _State.CLOSED
    ok("starts in CLOSED state")

def test_cb_trips_after_threshold():
    cb = GeminiCircuitBreaker(failure_threshold=3, recovery_timeout_s=60, call_timeout_s=0.05)
    def bad(): raise RuntimeError("boom")
    for _ in range(3):
        cb.call(bad)
    assert cb._state == _State.OPEN, f"expected OPEN, got {cb._state}"
    ok("CLOSED → OPEN after 3 consecutive failures")

def test_cb_fast_fails_when_open():
    cb = GeminiCircuitBreaker(failure_threshold=1, recovery_timeout_s=9999, call_timeout_s=5)
    def bad(): raise RuntimeError("boom")
    cb.call(bad)                  # first failure → OPEN
    called = []
    def should_not_be_called(): called.append(True)
    result = cb.call(should_not_be_called)
    assert result is None
    assert called == [], "fn was called even though breaker is OPEN"
    ok("OPEN state fast-fails (fn never called)")

def test_cb_half_open_probe_success():
    cb = GeminiCircuitBreaker(failure_threshold=1, recovery_timeout_s=0.05, call_timeout_s=5)
    def bad(): raise RuntimeError("boom")
    cb.call(bad)                   # → OPEN
    time.sleep(0.1)                # wait recovery_timeout
    result = cb.call(lambda: "ok") # → HALF_OPEN probe → success → CLOSED
    assert result == "ok"
    assert cb._state == _State.CLOSED
    ok("OPEN → HALF_OPEN → CLOSED on successful probe")

def test_cb_timeout():
    cb = GeminiCircuitBreaker(failure_threshold=5, recovery_timeout_s=60, call_timeout_s=0.1)
    def slow(): time.sleep(10)
    result = cb.call(slow)
    assert result is None
    ok("call times out → returns None (no exception propagated)")

def test_cb_success_resets_failures():
    cb = GeminiCircuitBreaker(failure_threshold=3, recovery_timeout_s=60, call_timeout_s=5)
    def bad():  raise RuntimeError("boom")
    def good(): return "ok"
    cb.call(bad)   # 1 failure
    cb.call(bad)   # 2 failures
    cb.call(good)  # success — should reset
    assert cb._failure_count == 0
    assert cb._state == _State.CLOSED
    ok("success resets failure count (won't trip from leftover failures)")

test_cb_starts_closed()
test_cb_trips_after_threshold()
test_cb_fast_fails_when_open()
test_cb_half_open_probe_success()
test_cb_timeout()
test_cb_success_resets_failures()

# ══════════════════════════════════════════════════════════════════════════════
# 2. RATE LIMITER (fakeredis)
# ══════════════════════════════════════════════════════════════════════════════
section("2. Rate Limiter (fakeredis)")

try:
    import fakeredis
    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False
    print(f"  {YELLOW}⚠️  fakeredis not installed — installing…{RESET}")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "fakeredis", "-q"], check=True)
    import fakeredis
    HAS_FAKEREDIS = True

from app.middleware.rate_limiter import _get_limit, _get_identity, RateLimitMiddleware

def test_route_limits():
    assert _get_limit("POST", "/api/v1/hackrx/upload")          == (5,  60)
    assert _get_limit("POST", "/api/v1/hackrx/run")             == (20, 60)
    assert _get_limit("GET",  "/api/v1/hackrx/jobs/abc/status") == (60, 60)
    assert _get_limit("GET",  "/health")                        == (30, 60)
    assert _get_limit("GET",  "/anything-else")                 == (60, 60)
    ok("route limit table correct")

def test_identity_bearer():
    req = MagicMock()
    req.headers = {"Authorization": "Bearer mytoken123"}
    req.client.host = "1.2.3.4"
    identity = _get_identity(req)
    assert identity.startswith("user:"), f"expected user: prefix, got {identity}"
    # same token → same identity
    identity2 = _get_identity(req)
    assert identity == identity2
    ok("Bearer token → consistent user identity (hashed)")

def test_identity_ip():
    req = MagicMock()
    req.headers = {}
    req.client.host = "192.168.1.1"
    identity = _get_identity(req)
    assert identity == "ip:192.168.1.1"
    ok("no token → IP-based identity")

def test_identity_forwarded():
    req = MagicMock()
    req.headers = {"X-Forwarded-For": "10.0.0.1, 172.16.0.1"}
    req.client.host = "127.0.0.1"
    identity = _get_identity(req)
    assert identity == "ip:10.0.0.1", f"got {identity}"
    ok("X-Forwarded-For → first IP used")

async def test_rate_limit_enforcement():
    """Simulate 7 requests against a limit of 5 using fakeredis."""
    fake_redis = fakeredis.FakeRedis(decode_responses=True)

    # Patch redis.from_url to return our fakeredis instance
    import app.middleware.rate_limiter as rl_mod
    original_from_url = rl_mod.redis_lib.from_url

    responses = []

    async def run_requests():
        from starlette.testclient import TestClient
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse

        inner_app = FastAPI()

        @inner_app.post("/api/v1/hackrx/upload")
        async def upload():
            return {"ok": True}

        # Patch the middleware's Redis to use fakeredis
        mw = RateLimitMiddleware(inner_app, "redis://fake")
        mw._redis = fake_redis

        from starlette.requests import Request as StarletteRequest
        from starlette.responses import Response
        from starlette.datastructures import Headers

        async def fake_next(request):
            return Response(content='{"ok":true}', media_type="application/json", status_code=200)

        for i in range(7):
            scope = {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/hackrx/upload",
                "query_string": b"",
                "headers": [(b"host", b"localhost")],
                "client": ("1.2.3.4", 1234),
            }
            request = StarletteRequest(scope)
            resp = await mw.dispatch(request, fake_next)
            responses.append(resp.status_code)

    await run_requests()

    assert responses[:5] == [200, 200, 200, 200, 200], f"Expected 5 OK, got {responses[:5]}"
    assert responses[5]  == 429, f"Expected 429 on 6th, got {responses[5]}"
    assert responses[6]  == 429, f"Expected 429 on 7th, got {responses[6]}"
    ok("5 requests → 200, 6th/7th → 429 (rate limit enforced)")

test_route_limits()
test_identity_bearer()
test_identity_ip()
test_identity_forwarded()
asyncio.run(test_rate_limit_enforcement())

# ══════════════════════════════════════════════════════════════════════════════
# 3. STRUCTURED JSON LOGGING
# ══════════════════════════════════════════════════════════════════════════════
section("3. Structured JSON Logging")

from app.middleware.logging import configure_json_logging, request_id_ctx, get_request_id

def test_json_log_format():
    configure_json_logging()
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    from app.middleware.logging import _JsonFormatter
    handler.setFormatter(_JsonFormatter())
    log = logging.getLogger("test.json")
    log.handlers = [handler]
    log.setLevel(logging.DEBUG)
    log.propagate = False
    log.info("hello world", extra={"latency_ms": 42.1, "status_code": 200})
    output = stream.getvalue().strip()
    data = json.loads(output)
    assert data["message"]    == "hello world"
    assert data["level"]      == "INFO"
    assert data["latency_ms"] == 42.1
    assert data["status_code"] == 200
    assert "ts" in data
    ok("log line is valid JSON with all expected fields")

def test_request_id_context():
    token = request_id_ctx.set("test-req-id-123")
    assert get_request_id() == "test-req-id-123"
    request_id_ctx.reset(token)
    ok("request_id ContextVar propagates correctly")

def test_request_id_default():
    # After reset, should return default "-"
    assert get_request_id() == "-"
    ok("request_id defaults to '-' when not set")

test_json_log_format()
test_request_id_context()
test_request_id_default()

# ══════════════════════════════════════════════════════════════════════════════
# 4. HEALTH ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════
section("4. /health Endpoint")

async def test_health_all_ok():
    from app.routers import health as health_mod

    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    mock_celery = MagicMock()
    mock_celery.control.inspect.return_value.ping.return_value = {
        "celery@worker1": {"ok": "pong"}
    }

    with patch("app.routers.health.redis_lib.from_url", return_value=mock_redis), \
         patch("app.routers.health.get_celery_app",     return_value=mock_celery):
        resp = await health_mod.health()

    body = json.loads(resp.body)
    assert resp.status_code               == 200
    assert body["status"]                 == "healthy"
    assert body["checks"]["redis"]["status"]          == "ok"
    assert body["checks"]["celery_workers"]["status"] == "ok"
    assert "celery@worker1" in body["checks"]["celery_workers"]["workers"]
    ok("/health returns 200 + 'healthy' when Redis and Celery are up")

async def test_health_redis_down():
    from app.routers import health as health_mod

    mock_redis = MagicMock()
    mock_redis.ping.side_effect = Exception("Connection refused")

    mock_celery = MagicMock()
    mock_celery.control.inspect.return_value.ping.return_value = {
        "celery@worker1": {"ok": "pong"}
    }

    with patch("app.routers.health.redis_lib.from_url", return_value=mock_redis), \
         patch("app.routers.health.get_celery_app",     return_value=mock_celery):
        resp = await health_mod.health()

    body = json.loads(resp.body)
    assert resp.status_code               == 503
    assert body["status"]                 == "degraded"
    assert body["checks"]["redis"]["status"] == "error"
    ok("/health returns 503 + 'degraded' when Redis is down")

async def test_health_no_workers():
    from app.routers import health as health_mod

    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    mock_celery = MagicMock()
    mock_celery.control.inspect.return_value.ping.return_value = None  # no workers

    with patch("app.routers.health.redis_lib.from_url", return_value=mock_redis), \
         patch("app.routers.health.get_celery_app",     return_value=mock_celery):
        resp = await health_mod.health()

    body = json.loads(resp.body)
    assert resp.status_code                           == 503
    assert body["status"]                             == "degraded"
    assert body["checks"]["celery_workers"]["status"] == "error"
    ok("/health returns 503 + 'degraded' when no Celery workers respond")

asyncio.run(test_health_all_ok())
asyncio.run(test_health_redis_down())
asyncio.run(test_health_no_workers())

# ══════════════════════════════════════════════════════════════════════════════
# 5. docker-compose.yml bug fix
# ══════════════════════════════════════════════════════════════════════════════
section("5. docker-compose.yml — Beat Scheduler Bug Fix")

with open("docker-compose.yml") as f:
    dc = f.read()

if "django_celery_beat" in dc:
    fail("docker-compose.yml still contains django_celery_beat scheduler")
elif "celery.beat:PersistentScheduler" in dc:
    ok("Celery Beat uses PersistentScheduler (not Django's)")
else:
    fail("docker-compose.yml beat scheduler line not found at all")

# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{'═'*60}")
total = passed + failed
print(f"{BOLD}  Results: {GREEN}{passed} passed{RESET}{BOLD}, {RED}{failed} failed{RESET}{BOLD} / {total} total{RESET}")
print(f"{'═'*60}\n")
sys.exit(0 if failed == 0 else 1)
