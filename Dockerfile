FROM python:3.11-slim

WORKDIR /app

# Memory and execution optimizations for low-resource environments (512MB RAM)
ENV PYTHONUNBUFFERED=1 \
    MALLOC_TRIM_THRESHOLD_=100000 \
    C_FORCE_ROOT=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libopenjp2-7 \
    libtiff-dev \
    libjpeg-dev \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories, sanitize line endings, and ensure start.sh is executable
RUN mkdir -p /app/known_documents /app/temp_files /app/celery_beat_schedule \
    && sed -i 's/\r$//' /app/start.sh \
    && chmod +x /app/start.sh

# Default command runs start.sh (starts Celery worker + beat in background, Uvicorn in foreground)
CMD ["/app/start.sh"]
