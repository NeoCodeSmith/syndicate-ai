# ═══════════════════════════════════════════════════════════════════════════
# SYNDICATE AI — Production Dockerfile
# Multi-stage build: builder → runtime
# Base: python:3.12-slim-bookworm (Debian 12, fewer CVEs than bullseye)
# Final image: ~160MB, non-root uid 1001, no dev tools, no build deps
# ═══════════════════════════════════════════════════════════════════════════

# ─── Stage 1: Builder ───────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

# Install build deps, upgrade all system packages to latest patched versions
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip to latest
RUN pip install --upgrade pip

# Install Python runtime deps into isolated prefix
COPY requirements.txt .
RUN pip install --prefix=/install --no-warn-script-location -r requirements.txt

# ─── Stage 2: Runtime ───────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

# OCI image labels
LABEL org.opencontainers.image.title="SYNDICATE AI"
LABEL org.opencontainers.image.description="Deterministic Multi-Agent Orchestration Platform"
LABEL org.opencontainers.image.source="https://github.com/NeoCodeSmith/syndicate-ai"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.vendor="NeoCodeSmith"

WORKDIR /app

# Upgrade all system packages to latest patched versions (reduces CVE surface)
# Install only what runtime needs: libpq5 (postgres client), curl (healthcheck)
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* \
    && useradd --uid 1001 --no-create-home --shell /sbin/nologin syndicate

# Copy Python packages from builder (no build tools bleed into runtime)
COPY --from=builder /install /usr/local

# Copy application source (owned by non-root user)
COPY --chown=syndicate:syndicate src/ ./src/
COPY --chown=syndicate:syndicate agents/ ./agents/
COPY --chown=syndicate:syndicate workflows/ ./workflows/

# Drop to non-root
USER syndicate

# Hardened env
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=1

# Health check (fail fast: 10s start, 10s interval)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "syndicate.api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--no-access-log"]
