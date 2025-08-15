# Use a slim Python image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Create a non-root user
RUN useradd --create-home --shell /bin/bash appuser

# Copy requirements and install dependencies
COPY requirements.txt .
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r requirements-dev.txt

# Copy configuration files
COPY pyproject.toml pytest.ini ./

# Copy the application code
COPY . .

# Install cline
RUN pip install --no-cache-dir cline

# Change ownership of the app directory to the non-root user
RUN chown -R appuser:appuser /app

# Switch to the non-root user
USER appuser

# Declare a volume for persistent data
VOLUME /app/data

# Command to run the application
CMD ["python", "src/main.py"]
