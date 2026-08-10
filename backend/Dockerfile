# ==============================================================================
# AssistMe Backend — Production Dockerfile (Fast & Stable)
# ==============================================================================

FROM python:3.12-slim-bookworm AS runner

WORKDIR /app

# Create unprivileged non-root user for security
RUN groupadd -r assistme && useradd -r -g assistme -d /app -s /sbin/nologin assistme

# Install pre-compiled binary Python wheels directly (with extended timeout & retries for slow connections)
COPY requirements.txt .
RUN pip install --default-timeout=1000 --retries=10 --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /app

RUN chown -R assistme:assistme /app
USER assistme

ENV PYTHONPATH=/app

EXPOSE 8000

# Native Python healthcheck (no extra OS packages required)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--proxy-headers"]
