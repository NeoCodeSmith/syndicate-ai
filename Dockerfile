# ═══════════════════════════════════════════════════════════════════════════
# SYNDICATE AI — Production Dockerfile
# Multi-stage build: builder → runtime
# Final image: ~180MB, non-root user, no dev dependencies
# ═══════════════════════════════════════════════════════════════════════════

# ─── Stage 1: Builder ───────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into /install
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-warn-script-location -r requirements.txt

# ─── Stage 2: Runtime ───────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Metadata
LABEL org.opencontainers.image.title="SYNDICATE AI"
LABEL org.opencontainers.image.description="Deterministic Multi-Agent Orchestration Platform"
LABEL org.opencontainers.image.source="https://github.com/NeoCodeSmith/syndicate-ai"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Runtime system dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1001 --create-home --shell /bin/bash syndicate

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY --chown=syndicate:syndicate src/ ./src/
COPY --chown=syndicate:syndicate agents/ ./agents/
COPY --chown=syndicate:syndicate workflows/ ./workflows/

# Switch to non-root user
USER syndicate

# Environment
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default: API server
EXPOSE 8000
CMD ["uvicorn", "syndicate.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
