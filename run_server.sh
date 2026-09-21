#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

mkdir -p logs
LOG_FILE="logs/pipeline_$(date +%Y%m%d).log"
LOCK_FILE="/tmp/betagent_run_server.lock"

# Защита от двойного запуска из cron
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$(date)] Пропуск: run_server.sh уже выполняется" >> "$LOG_FILE"
  exit 0
fi

# Подгружаем окружение
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  source "$PROJECT_DIR/.env"
  set +a
fi

echo "[$(date)] Старт run_server.sh" >> "$LOG_FILE"

# Основной прогон
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi
if "$PYTHON_BIN" run_pipeline.py --now >> "$LOG_FILE" 2>&1; then
  echo "[$(date)] run_pipeline.py --now OK" >> "$LOG_FILE"
  # Telegram notifications are handled inside run_pipeline.py
  echo "[$(date)] Прогон завершён" >> "$LOG_FILE"
else
  echo "[$(date)] run_pipeline.py --now FAILED" >> "$LOG_FILE"
  exit 1
fi
