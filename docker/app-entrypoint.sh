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

# 背景服務（排程器 / automation ticker）已改由 DB advisory-lock leader 選舉確保跨 worker/副本
# 僅單一執行，故 WEB_CONCURRENCY 可 >1；此處據以啟用多 worker。
if [ "$WEB_CONCURRENCY" != "1" ]; then
    set -- "$@" --workers "$WEB_CONCURRENCY"
fi

exec "$@"
