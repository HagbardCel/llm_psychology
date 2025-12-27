# Multi-stage build for optimized development and production images
# Uses UV package manager for 10-100x faster dependency installation

# ============================================
# Base stage: System dependencies + UV
# ============================================
FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies and UV
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

# ============================================
# Dependencies stage: Install Python packages
# ============================================
FROM base AS dependencies

# Copy requirements files
COPY requirements.txt pyproject.toml ./

# Install production dependencies with UV, using the PyTorch CPU index as an additional source.
# This ensures that torch, torchvision, and torchaudio are fetched as CPU-only builds.
RUN uv pip install --system --no-cache-dir -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match

# ============================================
# Development stage: Add dev dependencies
# ============================================
FROM dependencies AS development

# Copy dev requirements and install
COPY requirements-dev.txt ./
RUN uv pip install --system -r requirements-dev.txt

# Copy application source code and configuration
COPY pyproject.toml pytest.ini ./
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY deployment_validation.py ./
COPY data/ ./data/

# Install the backend package in editable mode for live reload
RUN uv pip install --system -e .

# Set environment for development
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Declare a volume for persistent data
VOLUME /app/data

# Command to run the application
CMD ["python", "-m", "psychoanalyst_app.server"]

# ============================================
# Production stage: Minimal final image
# ============================================
FROM dependencies AS production

# Copy the application code and configuration
COPY pyproject.toml ./
COPY src/ ./src/
COPY data/ ./data/

# Install the backend package
RUN uv pip install --system .

# Set environment for production
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Declare a volume for persistent data
VOLUME /app/data

# Command to run the application
CMD ["python", "-m", "psychoanalyst_app.server"]
