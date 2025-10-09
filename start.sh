#!/bin/bash

echo "Running database initialization & migration..."
python3 database_init.py --auto-fix

if [ $? -ne 0 ]; then
    echo "Database initialization failed. Aborting server start."
    exit 1
fi

echo "Starting server in background..."
uvicorn app.main:app --host 0.0.0.0 --port 9999 --reload &
PID=$!
echo $PID > server.pid
echo "Server started with PID: ${PID}. PID saved to server.pid"
