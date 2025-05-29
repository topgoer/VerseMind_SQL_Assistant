# Build stage - use simple Python slim image
FROM python:3.12-slim AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install build dependencies 
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy requirements
COPY requirements.txt .

# Install dependencies with build isolation
RUN pip wheel --no-cache-dir --wheel-dir=/build/wheels -r requirements.txt

# Final stage - use simple Python slim image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Update system and install only required runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libpq5 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    # Create non-root user
    useradd -m -d /app appuser

WORKDIR /app

# Copy built wheels from builder stage
COPY --from=builder /build/wheels /wheels

# Install packages from wheels and clean up in a single layer
RUN pip install --no-index --no-cache-dir --find-links=/wheels /wheels/* && \
    rm -rf /wheels && \
    mkdir -p /app/static && \
    chown -R appuser:appuser /app

# Copy application code and static files
COPY --chown=appuser:appuser . .

# Verify static files and set proper permissions as final configuration steps
RUN ls -la /app/static && \
    find /app -type d -exec chmod 755 {} \; && \
    find /app -type f -exec chmod 644 {} \;

# Set non-root user
USER appuser

# Expose port
EXPOSE 8000

# Start the application
CMD ["uvicorn", "sql_assistant.main:app", "--host", "0.0.0.0", "--port", "8000"]
