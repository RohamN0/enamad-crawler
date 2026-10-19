# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System dependencies:
#   libgl1 / libgl1-mesa-glx  -> opencv-python
#   libgomp1                  -> scipy
#   libsm6, libxext6, libxrender1 -> opencv / pillow
#   build-essential, gcc      -> compiling scipy/numpy wheels if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libgl1 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender1 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better layer caching).
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source.
COPY src ./src
COPY README.md ./

# Cache directory for trustseal detail pages (can be overridden by a volume).
ENV ENAMAD_CACHE_DIR="/app/.cache/trustseal" \
    ENAMAD_API_KEY="" \
    PORT=8000 \
    PYTHONPATH=/app

EXPOSE 8000

# Run the API server. 0.0.0.0 so it is reachable from docker-compose host mapping.
CMD ["python", "src/api.py"]
