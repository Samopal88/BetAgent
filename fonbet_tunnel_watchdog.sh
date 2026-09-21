#!/bin/bash
CODE=$(curl -s --max-time 5 --socks5 127.0.0.1:1081 \
  -H "Referer: https://fon.bet/" \
  "https://line-lb54-w.bk6bba-resources.com/ma/events/listBase?lang=ru&scopeMarket=1600" \
  -o /dev/null -w "%{http_code}" 2>/dev/null)

if [ "$CODE" != "200" ]; then
    systemctl restart fonbet-tunnel
    sleep 5
    cd /root/betagent
    source .env
    curl -s -X POST "https://api.telegram.org/bot${CLIENT_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${OWNER_CHAT_ID}" \
      -d "text=⚠️ Fonbet tunnel упал (код: ${CODE}) — перезапущен"
fi
