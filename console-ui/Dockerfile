# Console UI Service Dockerfile
# Uses UV package manager for faster dependency installation

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install UV package manager
RUN pip install --no-cache-dir uv

# Create non-root user
RUN useradd --create-home --shell /bin/bash consoleuser

# Copy requirements and install dependencies with UV
COPY requirements.txt ./
RUN uv pip install --system -r requirements.txt

# Copy the console UI application code
COPY . .

# Change ownership to non-root user
RUN chown -R consoleuser:consoleuser /app

# Switch to non-root user
USER consoleuser

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Command to run the console UI
CMD ["python", "main.py"]
