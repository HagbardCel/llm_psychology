# Use a slim Python image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY src/ ./src/
COPY tests/ ./tests/

# Declare a volume for persistent data
VOLUME /app/data

# Command to run the application
CMD ["python", "src/main.py"]
