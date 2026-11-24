#!/usr/bin/env sh
# Dev entrypoint: apply migrations, then start the API with auto-reload.
set -e
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app
