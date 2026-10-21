# ======================================================================
# TT NOTES & VOXLIVE AI - PRODUCTION CLOUD DOCKERFILE
# Compatible with Render, Railway, Google Cloud Run, & Fly.io
# ======================================================================

FROM python:3.11-slim

# Install system dependencies including ffmpeg for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency specifications and install
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY server.py .
COPY database.py .
COPY universal_extractor.py .
COPY notes_generator.py .
COPY index.html .
COPY voxlive.db .

# Expose standard web port
EXPOSE 8000

# Run FastAPI server binding to the environment's assigned PORT
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
