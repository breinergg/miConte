# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# miConte backend — Dockerfile
#
# Build strategy: uv installs dependencies from uv.lock into /app/.venv,
# then the final stage copies only the venv and the application source.
# No build tools, no pip, no compiler caches reach the final image.
#
# Single-worker constraint: LoginTransactionStore and OAuthTransactionStore are
# in-memory; running more than one Uvicorn worker would break the OIDC and
# YouTube OAuth flows. Keep --workers 1 until both stores are migrated to Redis
# or another shared backend.
# ─────────────────────────────────────────────────────────────────────────────

ARG PYTHON_VERSION=3.15.2

# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS builder

# Install uv (exact version pinned from uv.lock)
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv

WORKDIR /app

# Build-time system dependencies required to compile pandas from source.
# pandas 2.x (pulled by statsmodels) has no pre-built wheel for cp315 linux/aarch64.
# These tools stay in the builder stage only — the runtime stage is a fresh slim image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ gfortran pkg-config meson ninja-build \
        libopenblas-dev liblapack-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency manifests first — layer is cached until they change
COPY pyproject.toml uv.lock ./

# Install only production dependencies (no dev extras) into an explicit venv.
# --frozen: refuse to update uv.lock (reproducible build).
# --no-install-project: we copy src separately so the venv is pure deps.
RUN uv sync --frozen --no-dev --no-install-project --python python3.15

# Copy application source and README (hatchling requires README.md for the build)
COPY src/ ./src/
COPY README.md ./
RUN uv sync --frozen --no-dev --no-editable --python python3.15

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS runtime

# Create a non-root user
RUN groupadd --gid 1001 appgroup \
 && useradd --uid 1001 --gid appgroup --no-create-home --shell /sbin/nologin appuser

WORKDIR /app

# Copy the virtual environment and installed package from the build stage.
# Build and runtime both use /app so venv shebangs remain valid.
COPY --from=builder /app/.venv /app/.venv

# Copy Alembic configuration so migrations can be run explicitly
COPY alembic.ini ./
COPY alembic/ ./alembic/

# Application source is inside the venv as an installed package — no extra copy needed
# Activate the venv by prepending its bin directory to PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Default to production mode; override to development or testing via env var
    MICONTE_ENVIRONMENT=production \
    # Analytics real-data disabled by default (requires Google approval)
    MICONTE_ANALYTICS_REAL_DATA_ENABLED=false

# All sensitive configuration is supplied at runtime via environment variables —
# see .env.example for the full list. No secrets are baked into this image.

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=4); sys.exit(0)"

# Single worker — required while LoginTransactionStore / OAuthTransactionStore
# are in-memory. See single-process limitation in security/login.py and security/oauth.py.
CMD ["uvicorn", "miconte.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
