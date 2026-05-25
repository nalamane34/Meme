#!/bin/sh
# Run DB migrations, then exec the CMD (uvicorn by default).
# Postgres readiness is enforced via docker-compose healthcheck; if you're
# running this outside compose, make sure $DATABASE_URL is reachable first.
set -e

echo "[entrypoint] running alembic migrations"
alembic upgrade head

echo "[entrypoint] starting: $*"
exec "$@"
