#!/bin/sh
set -eu

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-9999}"
UVICORN_LOG_LEVEL="${UVICORN_LOG_LEVEL:-info}"
UVICORN_PROXY_HEADERS="${UVICORN_PROXY_HEADERS:-1}"
FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"
SKIP_DATABASE_BOOTSTRAP="${SKIP_DATABASE_BOOTSTRAP:-0}"

if [ "$SKIP_DATABASE_BOOTSTRAP" != "1" ]; then
    echo "Running database bootstrap..."
    uv run python database_init.py
else
    echo "Skipping database bootstrap because SKIP_DATABASE_BOOTSTRAP=1"
fi

set -- uv run uvicorn app.main:app --host "$HOST" --port "$PORT" --log-level "$UVICORN_LOG_LEVEL"

if [ "$UVICORN_PROXY_HEADERS" = "1" ]; then
    set -- "$@" --proxy-headers --forwarded-allow-ips "$FORWARDED_ALLOW_IPS"
fi

if [ "$WEB_CONCURRENCY" != "1" ]; then
    echo "Warning: WEB_CONCURRENCY=$WEB_CONCURRENCY, but the in-process scheduler is only safe with a single worker." >&2
fi

exec "$@"
