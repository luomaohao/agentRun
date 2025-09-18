FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src src/
COPY main.py .
COPY examples examples/

# Create non-root user
RUN useradd -m -u 1000 workflow && \
    chown -R workflow:workflow /app

# Create directories for logs and data
RUN mkdir -p /app/logs /app/data && \
    chown -R workflow:workflow /app/logs /app/data

# Switch to non-root user
USER workflow

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/monitoring/health || exit 1

# Default environment variables
ENV PYTHONUNBUFFERED=1
ENV API_HOST=0.0.0.0
ENV API_PORT=8000
ENV API_RELOAD=false

# Run the application
CMD ["python", "main.py"]
