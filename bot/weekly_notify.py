#!/usr/bin/env python3
"""Еженедельное уведомление подписчикам со статистикой и напоминанием о кабинете."""
import os, sys, asyncio
from datetime import datetime

from pathlib import Path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
_env = BASE_DIR / '.env'
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

import psycopg2, psycopg2.extras, sqlite3
from telegram import Bot
from telegram.constants import ParseMode

BOT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
DB_URL = os.getenv("DATABASE_URL")
BETAGENT_DB = os.getenv("BETAGENT_DB", str(BASE_DIR / "betagent.db"))

WEEKLY_DEDUP_KEY = f"weekly_sub_{datetime.now().strftime('%Y_%W')}"

def _weekly_already_sent():
    conn = sqlite3.connect(BETAGENT_DB)
    row = conn.execute(
        "SELECT 1 FROM channel_sent_log WHERE mode='weekly_sub' AND key=?",
        (WEEKLY_DEDUP_KEY,)
    ).fetchone()
    conn.close()
    return row is not None

def _weekly_mark_sent():
    conn = sqlite3.connect(BETAGENT_DB)
    conn.execute(
        "INSERT OR IGNORE INTO channel_sent_log (mode,key,sent_at) VALUES (?,?,?)",
        ("weekly_sub", WEEKLY_DEDUP_KEY, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

async def main():
    if _weekly_already_sent():
        print("[weekly_sub] Уже отправлен"); return

    bot = Bot(token=BOT_TOKEN)
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Активные подписчики
    cur.execute("""
        SELECT u.telegram_id, u.first_name FROM users u
        JOIN subscriptions s ON s.user_id = u.id
        WHERE s.status = 'active' AND s.end_date > NOW()
        AND u.telegram_id IS NOT NULL
    """)
    users = cur.fetchall()

    # Недельная статистика — только закрытые ставки (won/lost), исключая pending
    cur.execute("""
        SELECT COUNT(*) as total,
               COUNT(*) FILTER (WHERE result = 'won') as won,
               COALESCE(SUM(CASE WHEN result = 'won' THEN 1 ELSE 0 END), 0) as wins,
               COALESCE(SUM(CASE WHEN result = 'lost' THEN 1 ELSE 0 END), 0) as losses
        FROM signals
        WHERE created_at >= NOW() - INTERVAL '7 days'
          AND result IN ('won', 'lost')
    """)
    weekly = cur.fetchone()

    # По видам спорта — только закрытые
    cur.execute("""
        SELECT sport, COUNT(*) as cnt,
               COUNT(*) FILTER (WHERE result = 'won') as won
        FROM signals
        WHERE created_at >= NOW() - INTERVAL '7 days'
          AND result IN ('won', 'lost')
        GROUP BY sport
    """)
    by_sport = cur.fetchall()

    conn.close()

    total = weekly["total"] if weekly else 0
    won = weekly["won"] if weekly else 0
    losses = weekly["losses"] if weekly else 0
    winrate = round(won / total * 100, 1) if total > 0 else 0

    sport_lines = []
    for row in by_sport:
        sport = row["sport"]
        icon = {"football": "⚽", "hockey": "🏒", "tennis": "🎾"}.get(sport, "📊")
        sport_lines.append(f"{icon} {sport}: {row['cnt']} ставок ({row['won']} выиграно)")

    if not sport_lines:
        sport_lines.append("📭 Нет ставок за неделю")

    sport_text = "\n".join(sport_lines)

    TEXT = (
        "📊 *Итоги недели BetAgent*\n\n"
        f"📋 Всего сигналов: *{total}*\n"
        f"✅ Выиграно: *{won}*\n"
        f"❌ Проиграно: *{losses}*\n"
        f"🎯 Winrate: *{winrate}%*\n\n"
        f"*По видам спорта:*\n{sport_text}\n\n"
        "─────────────────\n\n"
        "🌐 Не забывай про *bet-agent.ru* — личный кабинет со всей историей.\n"
        "Привяжи email: /cabinet → Настройки → Привязка email\n\n"
        "_Это займёт 1 минуту и сохранит доступ к сервису_"
    )

    sent = 0
    for u in users:
        try:
            await bot.send_message(
                chat_id=u["telegram_id"],
                text=TEXT,
                parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Не удалось отправить {u['telegram_id']}: {e}")
    print(f"Отправлено: {sent}/{len(users)}")
    if sent > 0:
        _weekly_mark_sent()

if __name__ == "__main__":
    asyncio.run(main())
