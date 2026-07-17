#!/bin/bash

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-9999}"
SERVER_PID_FILE="${SERVER_PID_FILE:-server.pid}"
SERVER_LOG="${SERVER_LOG:-server.log}"
UVICORN_RELOAD="${UVICORN_RELOAD:-1}"

# Same default policy as docker/app-entrypoint.sh when WEB_CONCURRENCY is unset/empty:
# resolved main DB engine (env DATABASE_URL or config.yaml) via the shared Python
# helper; env-pattern case is only a fallback when the helper cannot run.
_default_web_concurrency() {
    if value="$(uv run python scripts/print_inferred_web_concurrency.py 2>/dev/null)" \
        && [ -n "$value" ]; then
        echo "$value"
        return
    fi
    case "${DATABASE_URL:-}" in
        mysql://*|mysql+*|postgresql://*|postgresql+*|postgres://*|postgres+*)
            echo 5
            ;;
        *)
            echo 1
            ;;
    esac
}
# Keep WEB_CONCURRENCY itself untouched: overwriting an exported empty string
# would leak the resolved number into the uvicorn child process, and the runtime
# settings API would then misreport source=configured instead of inferred_default.
if [ -z "${WEB_CONCURRENCY:-}" ]; then
    RESOLVED_WEB_CONCURRENCY="$(_default_web_concurrency)"
else
    RESOLVED_WEB_CONCURRENCY="$WEB_CONCURRENCY"
fi

# Refuse to start when a server from a previous run is still alive, so the
# PID file is never overwritten while old processes keep holding the port.
if [ -f "$SERVER_PID_FILE" ]; then
    OLD_PID=$(cat "$SERVER_PID_FILE")
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Server already running with PID ${OLD_PID} (from ${SERVER_PID_FILE}). Run ./stop.sh first."
        exit 1
    fi
    echo "Removing stale PID file ${SERVER_PID_FILE} (PID ${OLD_PID} not running)."
    rm -f "$SERVER_PID_FILE"
fi

PORT_PIDS=$(lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null)
if [ -n "$PORT_PIDS" ]; then
    echo "Port ${PORT} is already in use by PID(s): $(echo "$PORT_PIDS" | tr '\n' ' '). Run ./stop.sh first."
    exit 1
fi

echo "Running database bootstrap..."
if ! uv run python database_init.py; then
    echo "Database initialization failed. Aborting server start."
    exit 1
fi

echo "Starting server in background..."
UVICORN_ARGS=(--host "$HOST" --port "$PORT" --proxy-headers --forwarded-allow-ips '*')
if [ "$UVICORN_RELOAD" = "1" ]; then
    # Watch only the source tree; watching the whole CWD (large .db files, .venv,
    # graphify-out, backups) makes the reload watcher spin at ~40% CPU.
    # Reload mode is single-process; multi-worker is ignored while reloading.
    UVICORN_ARGS+=(--reload --reload-dir app)
elif [ "$RESOLVED_WEB_CONCURRENCY" != "1" ]; then
    UVICORN_ARGS+=(--workers "$RESOLVED_WEB_CONCURRENCY")
fi
echo "WEB_CONCURRENCY=${RESOLVED_WEB_CONCURRENCY} UVICORN_RELOAD=${UVICORN_RELOAD}"
# nohup + log redirect: survive terminal close, and never block callers
# that capture this script's output (the background child would otherwise
# hold the stdout pipe open forever).
nohup uv run uvicorn app.main:app "${UVICORN_ARGS[@]}" </dev/null >> "$SERVER_LOG" 2>&1 &
PID=$!
echo $PID > "$SERVER_PID_FILE"
echo "Server started with PID: ${PID}. PID saved to ${SERVER_PID_FILE}. Logs: ${SERVER_LOG}"
