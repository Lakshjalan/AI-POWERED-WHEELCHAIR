# ==============================================================================
# OcuSteer Hub - Docker Container
# Dual-Modal Eye-Glance & Biopotential Assistive Vehicle System
# ==============================================================================

FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000

# Install runtime system dependencies for OpenCV & USB devices
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY laptop_hub/ ./laptop_hub/
COPY app.py .
COPY run.py .

# Expose Web Cockpit Dashboard port
EXPOSE 5000

# Container Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/api/telemetry || exit 1

# Start the OcuSteer Hub server
CMD ["python3", "app.py"]
