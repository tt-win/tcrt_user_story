#!/bin/bash

PORT="${PORT:-9999}"
SERVER_PID_FILE="${SERVER_PID_FILE:-server.pid}"
STOP_TIMEOUT="${STOP_TIMEOUT:-10}"

# Print a process and all of its descendants
# (uv run -> uvicorn reloader -> multiprocessing workers).
collect_tree() {
    local pid=$1 child
    echo "$pid"
    for child in $(pgrep -P "$pid" 2>/dev/null); do
        collect_tree "$child"
    done
}

alive_pids() {
    local pid
    for pid in "$@"; do
        kill -0 "$pid" 2>/dev/null && echo "$pid"
    done
}

TARGETS=""

if [ -f "$SERVER_PID_FILE" ]; then
    MAIN_PID=$(cat "$SERVER_PID_FILE")
    if [ -n "$MAIN_PID" ] && kill -0 "$MAIN_PID" 2>/dev/null; then
        TARGETS=$(collect_tree "$MAIN_PID")
    else
        echo "PID ${MAIN_PID} from ${SERVER_PID_FILE} is not running (stale PID file)."
    fi
else
    echo "No PID file (${SERVER_PID_FILE}); checking port ${PORT} for leftover processes."
fi

# Safety net: also target anything still listening on the server port,
# e.g. orphaned reload workers that outlived the recorded PID.
PORT_PIDS=$(lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null)
TARGETS=$(printf '%s\n%s\n' "$TARGETS" "$PORT_PIDS" | grep -v '^$' | sort -un)

if [ -z "$TARGETS" ]; then
    echo "Server is not running."
    rm -f "$SERVER_PID_FILE"
    exit 0
fi

echo "Stopping PID(s): $(echo $TARGETS | tr '\n' ' ')"
kill -TERM $TARGETS 2>/dev/null

for ((i = 0; i < STOP_TIMEOUT * 10; i++)); do
    [ -z "$(alive_pids $TARGETS)" ] && break
    sleep 0.1
done

REMAINING=$(alive_pids $TARGETS)
if [ -n "$REMAINING" ]; then
    echo "Still alive after ${STOP_TIMEOUT}s; sending SIGKILL to: $(echo $REMAINING | tr '\n' ' ')"
    kill -KILL $REMAINING 2>/dev/null
    sleep 0.5
fi

LEFT=$(lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null)
if [ -n "$LEFT" ]; then
    echo "Error: port ${PORT} is still in use by PID(s): $(echo "$LEFT" | tr '\n' ' '). Server not fully stopped."
    exit 1
fi

rm -f "$SERVER_PID_FILE"
echo "Server stopped."
