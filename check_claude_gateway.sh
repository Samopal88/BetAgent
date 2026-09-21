#!/usr/bin/env bash
set -euo pipefail

URL="https://api.aws-us-east-3.com"
STATE_FILE="/root/betagent/.claude_gateway_state"
LOG_FILE="/root/betagent/logs/claude_gateway_check.log"

# Telegram
BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT_ID="${TELEGRAM_CHAT_ID:-}"

mkdir -p /root/betagent/logs

timestamp() {
  date "+%Y-%m-%d %H:%M:%S"
}

send_tg() {
  local text="$1"
  curl -sS -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${text}" >/dev/null
}

check_url() {
  curl -k -sS -o /dev/null -w "%{http_code}" --max-time 10 "$URL" || echo "000"
}

HTTP_CODE="$(check_url)"

# Любой не-000 код = сервер отвечает
if [[ "$HTTP_CODE" != "000" ]]; then
  CURRENT="UP:$HTTP_CODE"
else
  CURRENT="DOWN"
fi

PREV="UNKNOWN"
if [[ -f "$STATE_FILE" ]]; then
  PREV="$(cat "$STATE_FILE" 2>/dev/null || echo UNKNOWN)"
fi

echo "[$(timestamp)] status=$CURRENT prev=$PREV" >> "$LOG_FILE"

# Шлём уведомление только при смене состояния
if [[ "$CURRENT" != "$PREV" ]]; then
  echo "$CURRENT" > "$STATE_FILE"

  if [[ "$CURRENT" == UP:* ]]; then
    send_tg "✅ Claude gateway ожил: $URL (HTTP ${HTTP_CODE})"
  else
    send_tg "❌ Claude gateway снова недоступен: $URL"
  fi
fi
