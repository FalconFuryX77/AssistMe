# ==============================================================================
# AssistMe Backend — Multi-Stage Production Dockerfile
# ==============================================================================

# --- Stage 1: Build & Dependency Wheel Cache ---
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# --- Stage 2: Minimal Production Runtime ---
FROM python:3.12-slim AS runner

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged non-root user
RUN groupadd -r assistme && useradd -r -g assistme -d /app -s /sbin/nologin assistme

# Copy installed wheels from builder
COPY --from=builder /root/.local /home/assistme/.local
ENV PATH=/home/assistme/.local/bin:$PATH
ENV PYTHONPATH=/app

# Copy application source code
COPY . /app

RUN chown -R assistme:assistme /app
USER assistme

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--proxy-headers"]
