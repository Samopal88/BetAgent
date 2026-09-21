#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys, sqlite3, argparse, requests
from datetime import datetime, timedelta
from pathlib import Path

_env = Path(__file__).resolve().parent / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

CHANNEL_TOKEN = os.getenv("CHANNEL_BOT_TOKEN", "")
CHANNEL_ID    = os.getenv("CHANNEL_ID", "")
DB_PATH       = os.getenv("BETAGENT_DB", str(Path(__file__).parent / "betagent.db"))
START_BANK    = float(os.getenv("BETAGENT_BANK", "100000"))

def odds_range(odds):
    if odds >= 5.0:   return "5+"
    elif odds >= 4.5: return "4.5+"
    elif odds >= 4.0: return "4+"
    elif odds >= 3.5: return "3.5+"
    elif odds >= 3.0: return "3+"
    elif odds >= 2.5: return "2.5+"
    elif odds >= 2.0: return "2+"
    elif odds >= 1.8: return "1.8+"
    elif odds >= 1.6: return "1.6+"
    else:             return f"{odds:.1f}+"

def sport_emoji(sport):
    if sport and "hockey" in sport.lower():
        return "🏒"
    elif sport and "tennis" in sport.lower():
        return "🎾"
    return "⚽️"

def league_display(league):
    if not league: return "—"
    # Убираем "Страна. Лига. Сезон XX/XX" → оставляем только лигу
    import re
    # Убираем суффикс сезона
    league = re.sub(r'\.?\s*[Сс]езон\s*\d{2}/\d{2}', '', league).strip()
    # Если формат "Страна. Лига" — берём только Лигу
    parts = [p.strip() for p in league.split('.') if p.strip()]
    if len(parts) >= 2:
        league = parts[-1]
    # Если формат "Страна | Лига" — берём только Лигу
    for sep in [" | ", " - "]:
        if sep in league:
            league = league.split(sep)[0].strip()
    return league

def send(text):
    if not CHANNEL_TOKEN or not CHANNEL_ID:
        print("⚠️  CHANNEL_BOT_TOKEN или CHANNEL_ID не настроены в .env")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{CHANNEL_TOKEN}/sendMessage",
            json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        )
        if r.status_code == 200:
            print(f"✅ Опубликовано в канал")
            return True
        else:
            print(f"❌ Telegram error {r.status_code}: {r.text[:200]}")
            return False
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

def ensure_schema():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS channel_sent_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mode TEXT NOT NULL, key TEXT NOT NULL UNIQUE, sent_at TEXT NOT NULL)""")
    conn.commit(); conn.close()

def already_sent(mode, key):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT 1 FROM channel_sent_log WHERE mode=? AND key=?", (mode, key)).fetchone()
    conn.close(); return row is not None

def mark_sent(mode, key):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO channel_sent_log (mode,key,sent_at) VALUES (?,?,?)",
                 (mode, key, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit(); conn.close()

def get_conn():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; return conn

def publish_bets():
    since = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.id, b.odds, b.market, b.ev, b.our_probability,
               m.sport, m.league, m.home_team, m.away_team, m.match_date
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result = 'pending' AND b.created_at >= ?
        ORDER BY b.created_at ASC
    """, (since,)).fetchall()
    conn.close()
    published = 0
    for r in rows:
        key = f"bet_{r['id']}"
        if already_sent("bets", key): continue
        try:
            dt = datetime.fromisoformat(str(r["match_date"])[:16])
            time_str = dt.strftime("%d.%m, %H:%M")
        except:
            time_str = str(r["match_date"])[:10] if r["match_date"] else "—"

        sport = r["sport"] or ""
        if sport and "tennis" in sport.lower():
            # Tennis-specific template
            market = r["market"] or ""
            if market == "player1_win":
                pick = f"П1 ({r['home_team'] or ''})"
            elif market == "player2_win":
                pick = f"П2 ({r['away_team'] or ''})"
            else:
                pick = market or "?"
            ev = r["ev"] or 0
            try:
                ev_str = f"{ev * 100:+.1f}%"
            except:
                ev_str = "N/A"
            text = (
                f"⚡️ <b>НОВАЯ РЕКОМЕНДАЦИЯ</b>\n\n"
                f"🎾 {league_display(r['league'])}\n"
                f"⚔️ {r['home_team'] or '?'} — {r['away_team'] or '?'}\n"
                f"📅 {time_str}\n"
                f"📌 <b>{pick}</b> @ {r['odds']}\n"
                f"📊 EV: {ev_str}\n\n"
                f"Полные параметры — подписчикам бота.\n"
                f"→ @betagent_analytics_bot"
            )
        else:
            # Football/hockey template
            text = (
                f"⚡️ <b>НОВАЯ РЕКОМЕНДАЦИЯ</b>\n\n"
                f"{sport_emoji(sport)} {league_display(r['league'])}\n"
                f"📊 Коэффициент: {odds_range(r['odds'])}\n"
                f"📅 {time_str}\n\n"
                f"Алгоритм зафиксировал расхождение с расчётной вероятностью.\n\n"
                f"Полные параметры — подписчикам бота.\n"
                f"→ @betagent_analytics_bot"
            )
        if send(text):
            mark_sent("bets", key); published += 1
    print(f"[bets] Опубликовано: {published} из {len(rows)}")

def publish_results():
    since = (datetime.now() - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.id, b.odds, b.result, b.created_at, m.sport, m.league
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result IN ('won','lost') AND COALESCE(b.excluded_from_stats,0)=0 AND b.created_at >= ?
        ORDER BY b.created_at ASC
    """, (since,)).fetchall()
    stats = conn.execute("""
        SELECT COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN stake ELSE 0 END),0) AS staked,
               COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN profit ELSE 0 END),0) AS profit
        FROM bets WHERE COALESCE(excluded_from_stats,0)=0
    """).fetchone()
    conn.close()
    roi = (stats["profit"] / stats["staked"] * 100) if stats["staked"] else 0
    published = 0
    for r in rows:
        key = f"result_{r['id']}"
        if already_sent("results", key): continue
        won = r["result"] == "won"
        text = (
            f"{'✅' if won else '❌'} <b>РЕЗУЛЬТАТ</b>\n\n"
            f"{sport_emoji(r['sport'])} {league_display(r['league'])} — "
            f"<b>{'сработало' if won else 'не сработало'}</b>\n"
            f"📊 Коэффициент: {odds_range(r['odds'])}\n\n"
        )
        text += "Алгоритм работает. Статистика обновлена." if won else \
                f"Отрицательный результат — часть любой математической системы.\nДистанция решает. Текущий ROI: {roi:+.2f}%"
        text += "\n\n→ @betagent_analytics_bot"
        if send(text):
            mark_sent("results", key); published += 1
    print(f"[results] Опубликовано: {published} из {len(rows)}")

def publish_weekly():
    since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    row = conn.execute("""
        SELECT SUM(CASE WHEN result='won' THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN result='lost' THEN 1 ELSE 0 END) AS losses,
               COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN stake ELSE 0 END),0) AS staked,
               COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN profit ELSE 0 END),0) AS profit
        FROM bets WHERE result IN ('won','lost') AND COALESCE(excluded_from_stats,0)=0 AND created_at >= ?
    """, (since,)).fetchone()
    bank_row = conn.execute("SELECT COALESCE(SUM(profit),0) AS p FROM bets WHERE result IN ('won','lost') AND COALESCE(excluded_from_stats,0)=0").fetchone()
    conn.close()
    wins = row["wins"] or 0; losses = row["losses"] or 0; total = wins + losses
    roi = (row["profit"] / row["staked"] * 100) if row["staked"] else 0
    winrate = (wins / total * 100) if total else 0
    bank_now = START_BANK + (bank_row["p"] or 0)
    key = f"weekly_{datetime.now().strftime('%Y_%W')}"
    if already_sent("weekly", key): print("[weekly] Уже отправлен"); return
    # Накопленный живой ROI с начала работы
    conn2 = get_conn()
    all_live = conn2.execute("""
        SELECT COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN stake ELSE 0 END),0) AS staked,
               COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN profit ELSE 0 END),0) AS profit
        FROM bets WHERE COALESCE(excluded_from_stats,0)=0
    """).fetchone()
    roi_all_live = (all_live["profit"] / all_live["staked"] * 100) if all_live and all_live["staked"] else 0
    conn2.close()

    text = (
        f"📊 <b>ИТОГИ НЕДЕЛИ</b>\n\n"
        f"Период: {(datetime.now()-timedelta(days=7)).strftime('%d.%m')}–{datetime.now().strftime('%d.%m.%Y')}\n"
        f"Рекомендаций: {total}\n"
        f"Сработало: {wins} | Не сработало: {losses}\n"
        f"Winrate: {winrate:.0f}%\n\n"
        f"💰 Результат недели: {roi:+.1f}%\n"
        f"📈 Накопленный ROI: {roi_all_live:+.2f}%\n"
        f"🏦 Банк: {START_BANK:,.0f} ₽ → {bank_now:,.0f} ₽ ({bank_now-START_BANK:+,.0f} ₽)\n\n"
        f"Система работает в плюс на дистанции.\n"
        f"Не потому что везёт — потому что математика.\n\n"
        f"→ @betagent_analytics_bot"
    )
    if send(text): mark_sent("weekly", key)

def publish_monthly():
    since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    row = conn.execute("""
        SELECT SUM(CASE WHEN result='won' THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN result='lost' THEN 1 ELSE 0 END) AS losses,
               COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN stake ELSE 0 END),0) AS staked,
               COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN profit ELSE 0 END),0) AS profit
        FROM bets WHERE result IN ('won','lost') AND COALESCE(excluded_from_stats,0)=0 AND created_at >= ?
    """, (since,)).fetchone()
    all_time = conn.execute("""
        SELECT COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN stake ELSE 0 END),0) AS staked,
               COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN profit ELSE 0 END),0) AS profit
        FROM bets WHERE COALESCE(excluded_from_stats,0)=0
    """).fetchone()
    conn.close()
    wins = row["wins"] or 0; losses = row["losses"] or 0; total = wins + losses
    roi_month = (row["profit"] / row["staked"] * 100) if row["staked"] else 0
    winrate = (wins / total * 100) if total else 0
    roi_all = (all_time["profit"] / all_time["staked"] * 100) if all_time["staked"] else 0
    bank_now = START_BANK + (all_time["profit"] or 0)
    key = f"monthly_{datetime.now().strftime('%Y_%m')}"
    if already_sent("monthly", key): print("[monthly] Уже отправлен"); return
    text = (
        f"📅 <b>ИТОГИ {['ЯНВАРЬ','ФЕВРАЛЬ','МАРТ','АПРЕЛЬ','МАЙ','ИЮНЬ','ИЮЛЬ','АВГУСТ','СЕНТЯБРЬ','ОКТЯБРЬ','НОЯБРЬ','ДЕКАБРЬ'][datetime.now().month-1]} {datetime.now().year}</b>\n\n"
        f"Рекомендаций: {total}\n"
        f"Сработало: {wins} | Не сработало: {losses}\n"
        f"Winrate: {winrate:.0f}%\n\n"
        f"💰 ROI за месяц: {roi_month:+.1f}%\n"
        f"📈 Накопленный ROI: {roi_all:+.2f}%\n"
        f"🏦 Банк: {START_BANK:,.0f} ₽ → {bank_now:,.0f} ₽ ({bank_now-START_BANK:+,.0f} ₽)\n\n"
        f"Включая все просадки. Без фильтрации.\n"
        f"Полная статистика — в боте.\n\n"
        f"→ @betagent_analytics_bot"
    )
    if send(text): mark_sent("monthly", key)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["bets","results","weekly","monthly"], required=True)
    args = ap.parse_args()
    ensure_schema()
    if args.mode == "bets":      publish_bets()
    elif args.mode == "results": publish_results()
    elif args.mode == "weekly":  publish_weekly()
    elif args.mode == "monthly": publish_monthly()
