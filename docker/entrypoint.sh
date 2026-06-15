#!/bin/sh
# Omniventory container entrypoint.
# Runs Alembic migrations against the volume-mounted SQLite DB, then
# hands off to the uvicorn server (the CMD from Dockerfile or compose).
set -e

echo "[entrypoint] Running Alembic migrations..."
alembic upgrade head

echo "[entrypoint] Starting application..."
exec "$@"
