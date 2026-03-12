#!/bin/bash

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-9999}"
SERVER_PID_FILE="${SERVER_PID_FILE:-server.pid}"
UVICORN_RELOAD="${UVICORN_RELOAD:-1}"

echo "Running database bootstrap..."
python3 database_init.py

if [ $? -ne 0 ]; then
    echo "Database initialization failed. Aborting server start."
    exit 1
fi

echo "Starting server in background..."
if [ "$UVICORN_RELOAD" = "1" ]; then
    uvicorn app.main:app --host "$HOST" --port "$PORT" --reload &
else
    uvicorn app.main:app --host "$HOST" --port "$PORT" &
fi
PID=$!
echo $PID > "$SERVER_PID_FILE"
echo "Server started with PID: ${PID}. PID saved to ${SERVER_PID_FILE}"
