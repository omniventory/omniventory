# =============================================================================
# Omniventory — multi-stage Dockerfile
# Single final image: FastAPI backend + built React frontend + SQLite volume.
#
# Stages:
#   1. frontend      — build the Vite/React SPA (node + pnpm)
#   2. backend-deps  — install Python deps with uv into /app/.venv at the
#                      final path, so console_script shebangs are correct
#   3. final         — slim Python runtime; copy app + venv + static assets
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: frontend build
# ---------------------------------------------------------------------------
FROM node:22-slim AS frontend

WORKDIR /build/frontend

# Enable pnpm via corepack (matches the packageManager field in package.json)
RUN corepack enable pnpm

# Install dependencies first (layer-cached unless lockfile changes).
# pnpm-workspace.yaml holds the allowBuilds policy; .npmrc sets approve-builds.
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/.npmrc ./
RUN pnpm install --frozen-lockfile

# Copy the rest of the frontend source and build
COPY frontend/ ./
RUN pnpm build

# ---------------------------------------------------------------------------
# Stage 2: backend Python deps
# Install into /app/.venv — the same absolute path used in the final image —
# so all console_script shebangs already point to /app/.venv/bin/python.
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS backend-deps

# Install uv
RUN pip install --no-cache-dir uv

# Pre-create the destination path so uv writes into the right place
WORKDIR /app

# Copy lock + project manifest and sync deps into /app/.venv
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# Stage 3: final runtime image
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS final

# Create a non-root user for security
RUN useradd --create-home --shell /bin/bash app

WORKDIR /app

# Copy the Python virtual environment (shebangs already point to /app/.venv/bin/python)
COPY --from=backend-deps /app/.venv /app/.venv

# Copy the backend application code
COPY backend/app ./app
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic

# Copy the built frontend static assets
COPY --from=frontend /build/frontend/dist ./static

# Declare the data directory as a volume so SQLite lives on the host, not in
# the image layer.  The directory is created so Docker can bind-mount it.
RUN mkdir -p /app/data && chown app:app /app/data /app

VOLUME ["/app/data"]

# Expose the application port
EXPOSE 8000

# Use the venv's Python / binaries
ENV PATH="/app/.venv/bin:$PATH"

# Default environment values (overridden at runtime via env / compose)
ENV ENVIRONMENT=production
ENV DATABASE_URL=sqlite:////app/data/omniventory.db

# Healthcheck: Python-based to avoid needing curl in the slim image
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request, sys; res = urllib.request.urlopen('http://127.0.0.1:8000/api/health'); sys.exit(0 if res.status == 200 else 1)"

# Entrypoint: run migrations, then start the app
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER app

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
