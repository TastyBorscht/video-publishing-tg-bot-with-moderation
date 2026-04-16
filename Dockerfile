# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY bot.py .
COPY database.py .
COPY localization.py .
COPY config.py .

# Copy configuration files (these will be overridden by volumes)
COPY localization.json .

# Create directory for database
RUN mkdir -p /app/data

# Run the bot
CMD ["python", "bot.py"]
