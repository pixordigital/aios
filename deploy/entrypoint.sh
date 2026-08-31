#!/bin/sh
set -e
echo "[entrypoint] alembic upgrade head..."
alembic upgrade head || echo "[entrypoint] alembic failed, continuing with create_all"
exec "$@"
