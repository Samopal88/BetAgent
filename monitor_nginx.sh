#!/usr/bin/env bash
# monitor_nginx.sh — Basic nginx availability monitor
# Checks both service status and HTTP availability

set -euo pipefail

# Env vars (optional override via .env)
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
ALERT_STATE_FILE="/tmp/nginx_monitor_last_alert"

# Load .env if exists
if [[ -f /root/betagent/.env ]]; then
    set -a
    source /root/betagent/.env
    set +a
fi

# Send Telegram alert (deduplication: only once per failure)
send_alert() {
    local msg="$1"

    # Check if already alerted
    if [[ -f "$ALERT_STATE_FILE" ]]; then
        last_alert=$(cat "$ALERT_STATE_FILE")
        if [[ "$last_alert" == "$msg" ]]; then
            return 0
        fi
    fi

    if [[ -n "$TELEGRAM_BOT_TOKEN" && -n "$TELEGRAM_CHAT_ID" ]]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            -d "text=🚨 NGINX MONITOR: ${msg}" \
            -d "parse_mode=HTML" >/dev/null 2>&1 || true

        echo "$msg" > "$ALERT_STATE_FILE"
    fi
}

# Clear alert state on success
clear_alert() {
    rm -f "$ALERT_STATE_FILE"
}

# Check 1: Service status
if ! systemctl is-active --quiet nginx; then
    send_alert "nginx service is NOT active (systemctl status failed)"
    exit 1
fi

# Check 2: HTTP availability (localhost:80)
if ! curl -f -s -o /dev/null --max-time 5 http://localhost:80; then
    send_alert "nginx HTTP check FAILED (localhost:80 not responding)"
    exit 1
fi

# All checks passed
clear_alert
exit 0
