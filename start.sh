#!/bin/bash
set -e

echo "=== Starting Enterprise Document Intelligence Platform (Low-Memory Mode) ==="

# 1. Start Celery worker with embedded Beat in a single solo process (-P solo -B)
# This eliminates 3 extra Python processes, saving ~250MB RAM for Render Free Tier (512MB limit)
echo "-> Starting Celery worker with embedded beat (solo pool)..."
celery -A app.celery_app worker -l info -P solo -B --schedule=/app/celery_beat_schedule/celerybeat-schedule &
CELERY_PID=$!

# Trap signals for graceful container shutdown
cleanup() {
    echo "Received shutdown signal. Stopping background worker..."
    kill -TERM "$CELERY_PID" 2>/dev/null || true
    wait "$CELERY_PID" 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# 2. Start FastAPI server
echo "-> Starting Uvicorn API on port ${PORT:-8000}..."
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 &
UVICORN_PID=$!

wait "$UVICORN_PID"
cleanup
