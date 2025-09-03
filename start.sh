#!/bin/bash
echo "Starting server in background..."
uvicorn app.main:app --host 0.0.0.0 --port 9999 --reload &
PID=$!
echo $PID > server.pid
echo "Server started with PID: ${PID}. PID saved to server.pid"
