#!/usr/bin/env python3
"""
settler_watchdog.py — алерт если ставка pending >6 часов после завершения матча
Запускать через cron каждый час.
"""
import sqlite3, os, requests
from datetime import datetime
from pathlib import Path

_env = Path(__file__).parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

DB_PATH = os.getenv("BETAGENT_DB", "/root/betagent/betagent.db")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("TG не настроен")
        return
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=10
    )

def check():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Ставки pending где матч завершён >6 часов назад
    rows = conn.execute("""
        SELECT b.id, b.market, b.odds, b.result,
               m.home_team, m.away_team, m.match_date, m.status,
               m.home_score, m.away_score
        FROM bets b
        JOIN matches m ON m.id = b.match_id
        WHERE b.result = 'pending'
          AND m.status = 'finished'
          AND m.updated_at < datetime('now', '-6 hours')
        ORDER BY m.match_date ASC
    """).fetchall()
    conn.close()

    if not rows:
        print(f"[{datetime.now():%H:%M}] Всё ок — подвисших ставок нет")
        return

    lines = [f"⚠️ <b>SETTLER АЛЕРТ</b> — {len(rows)} подвисших ставок!\n"]
    for r in rows:
        score = f"{r['home_score']}:{r['away_score']}" if r['home_score'] is not None else "?"
        lines.append(
            f"🔴 bet_id={r['id']} | {r['home_team']} — {r['away_team']}\n"
            f"   {r['match_date'][:10]} | {r['market']} @ {r['odds']} | счёт: {score}\n"
            f"   match_status: {r['status']}\n"
        )
    lines.append("Запусти: <code>python settler.py</code>")
    
    msg = "\n".join(lines)
    print(msg)
    send(msg)

if __name__ == "__main__":
    check()
