# Console UI Service Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Create non-root user
RUN useradd --create-home --shell /bin/bash consoleuser

# Copy requirements and install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the console UI application code
COPY . .

# Change ownership to non-root user
RUN chown -R consoleuser:consoleuser /app

# Switch to non-root user
USER consoleuser

# Command to run the console UI
CMD ["python", "main.py"]
