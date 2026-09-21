#!/bin/bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$PROJECT_DIR/logs"
PIDFILE="$PROJECT_DIR/logs/tg_bot.pid"
LOGFILE="$PROJECT_DIR/logs/tg_bot.log"

# Kill existing if running
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    kill -9 "$OLD_PID" 2>/dev/null
    sleep 1
fi

# Start new instance
cd "$PROJECT_DIR"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3)"
fi
nohup "$PYTHON_BIN" "$PROJECT_DIR/tg_bot.py" > "$LOGFILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PIDFILE"
echo "PID: $NEW_PID"
