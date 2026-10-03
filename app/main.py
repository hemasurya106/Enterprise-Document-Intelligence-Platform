import os
import logging

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .ask import router as ask_router
from .routers.health import router as health_router
from .routers.auth import router as auth_router
from .middleware.logging import StructuredLoggingMiddleware, configure_json_logging
from .middleware.rate_limiter import RateLimitMiddleware

# Switch the root logger to structured JSON output as early as possible
configure_json_logging(level=logging.INFO)

logger = logging.getLogger("app.startup")

UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
app = FastAPI(
    title="Enterprise Document Intelligence Platform",
    version="1.0.0",
    description="RAG pipeline with async ingestion via Celery + Redis + MongoDB Auth",
)

# ── Static files (login UI) ───────────────────────────────────────────────────
# Serves static/index.html at GET /
_static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir, html=True), name="static")

# ── Middleware (last-registered = outermost) ──────────────────────────────────
# Execution order on a request: Logging → RateLimit → CORS → route handler
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten to your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware, upstash_url=UPSTASH_URL, upstash_token=UPSTASH_TOKEN)
app.add_middleware(StructuredLoggingMiddleware)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router)     # POST /api/v1/auth/*  (public — no auth)
app.include_router(health_router)   # GET /health          (public — no auth)
app.include_router(ask_router)      # protected routes

logger.info("Application startup complete", extra={"upstash_url": UPSTASH_URL})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)