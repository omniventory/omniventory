#!/bin/sh
# Omniventory container entrypoint.
#
# NOTE: Alembic migrations are intentionally NOT run here. A dedicated one-shot
# `migrate` service in docker-compose.yml runs `alembic upgrade head`, and the
# `app` service starts only after it completes successfully
# (depends_on: condition: service_completed_successfully) — i.e. fail-closed:
# if migrations fail, the app is never started.
#
# This entrypoint just execs the given command:
#   - the `app` service runs the Dockerfile CMD (uvicorn)
#   - the `migrate` service overrides the command with `alembic upgrade head`
set -e

exec "$@"
