#!/bin/bash
set -e

echo "=== Starting Enterprise Document Intelligence Platform ==="

# 1. Start Celery worker in background
echo "-> Starting Celery worker..."
celery -A app.celery_app worker -l info --concurrency=2 &
CELERY_PID=$!

# 2. Start Celery beat in background
echo "-> Starting Celery beat..."
celery -A app.celery_app beat -l info --schedule=/app/celery_beat_schedule/celerybeat-schedule &
BEAT_PID=$!

# Trap signals for graceful container shutdown
cleanup() {
    echo "Received shutdown signal. Stopping Celery worker and beat..."
    kill -TERM "$CELERY_PID" 2>/dev/null || true
    kill -TERM "$BEAT_PID" 2>/dev/null || true
    wait "$CELERY_PID" 2>/dev/null || true
    wait "$BEAT_PID" 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# 3. Start FastAPI server
echo "-> Starting Uvicorn API on port ${PORT:-8000}..."
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
UVICORN_PID=$!

wait "$UVICORN_PID"
cleanup
