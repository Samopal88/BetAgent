#!/bin/bash
set -euo pipefail
cd /root/betagent
mkdir -p logs
LOG_FILE="logs/settle_$(date +%Y%m%d).log"
LOCK_FILE="/tmp/betagent_settle.lock"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$(date)] Пропуск: settle уже выполняется" >> "$LOG_FILE"
  exit 0
fi

if [ -f /root/betagent/.env ]; then
  set -a
  source /root/betagent/.env
  set +a
fi

echo "[$(date)] Старт settle" >> "$LOG_FILE"

source .venv/bin/activate

# Закрываем ставки
python3 -c "
from run_pipeline import task_settle
task_settle()
" >> "$LOG_FILE" 2>&1

# Watchdog — алерт если что-то зависло
python3 settler_watchdog.py >> "$LOG_FILE" 2>&1

echo "[$(date)] Settle завершён" >> "$LOG_FILE"
