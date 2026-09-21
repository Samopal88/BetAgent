#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BetAgent Analytics — push уведомления подписчикам.
Запускается из pipeline после генерации ставок и после settle.

Использование:
  python3 bot/notifier.py --mode bets
  python3 bot/notifier.py --mode results
"""
import os
import sys
import sqlite3
import argparse
import requests
import logging
from pathlib import Path

# Загружаем .env
_env = Path(__file__).parent.parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# Postgres для пользователей
sys.path.insert(0, str(Path(__file__).parent.parent))
from api.database import fetchall, fetchone, execute

CLIENT_BOT_TOKEN = os.getenv("CLIENT_BOT_TOKEN", "")
BASE_DIR = Path(__file__).resolve().parents[1]
SQLITE_DB = os.getenv("BETAGENT_DB", str(BASE_DIR / "betagent.db"))

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)


def tg_send(chat_id: int, text: str, reply_markup=None):
    if not CLIENT_BOT_TOKEN:
        return False
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        import json
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{CLIENT_BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        log.error(f"tg_send error: {e}")
        return False


def get_active_subscribers():
    return fetchall("""
        SELECT u.id, u.telegram_id, u.first_name,
               COALESCE(s.plan, 'none') as plan,
               CASE WHEN s.id IS NOT NULL AND s.end_date > now() THEN TRUE
                    ELSE FALSE END as has_subscription
        FROM users u
        LEFT JOIN subscriptions s ON s.user_id = u.id
            AND s.status = 'active'
            AND s.end_date > now()
        WHERE u.status = 'active'
          AND u.telegram_id IS NOT NULL
        ORDER BY s.plan DESC NULLS LAST
    """)


def was_notified(kind: str, key: str) -> bool:
    row = fetchone("""
        SELECT 1 FROM client_notifications
        WHERE kind=%s AND notify_key=%s
        LIMIT 1
    """, (kind, key))
    return row is not None


def mark_notified(kind: str, key: str, user_id: int):
    try:
        execute("""
            INSERT INTO client_notifications (kind, notify_key, user_id, created_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (kind, notify_key, user_id) DO NOTHING
        """, (kind, key, user_id))
    except Exception:
        pass


def fmt_new_signal(s: dict) -> str:
    market_map = {
        "draw": "Ничья (X)", "home": "П1", "away": "П2",
        "btts_yes": "Обе забьют", "over_2_5": "Тотал больше 2.5",
        "player1_win": f"П1 ({s.get('home_team', '')})",
        "player2_win": f"П2 ({s.get('away_team', '')})",
    }
    market = market_map.get(s.get("market", ""), s.get("market", ""))
    sport = s.get("sport", "")
    if sport == "tennis":
        icon = "🎾"
    elif sport == "football":
        icon = "⚽"
    else:
        icon = "🏒"
    league = s.get("league", "").split(".")[0].strip()
    date_str = str(s.get("match_date", ""))[:10]
    ev = s.get("ev") or 0
    try:
        ev = float(ev)
        ev_range = f"{max(0, round(ev*100-1.5)):.0f}–{round(ev*100+1.5):.0f}%"
    except Exception:
        ev_range = "3–7%"

    return (
        f"{icon} *{league}*\n"
        f"⚔️ {s.get('home_team', '')} — {s.get('away_team', '')}\n"
        f"📅 {date_str}\n"
        f"📌 *{market}* @ {s.get('odds', '?')}\n"
        f"📊 EV: {ev_range}\n"
    )


def fmt_result(s: dict) -> str:
    result = s.get("result", "")
    res_icon = "✅" if result == "won" else "❌"
    profit = s.get("profit") or 0
    profit_str = f"+{profit:.0f} ₽" if profit > 0 else f"{profit:.0f} ₽"
    market_map = {
        "draw": "X", "home": "П1", "away": "П2",
        "btts_yes": "ОЗ", "over_2_5": "Тб2.5",
        "player1_win": "П1", "player2_win": "П2",
    }
    market = market_map.get(s.get("market", ""), s.get("market", ""))
    sport = s.get("sport", "")
    if sport == "tennis":
        icon = "🎾"
    elif sport == "football":
        icon = "⚽"
    else:
        icon = "🏒"
    score = ""
    if s.get("home_score") is not None:
        score = f" {s['home_score']}:{s['away_score']}"
    return (
        f"{res_icon} {icon} *{s.get('home_team', '')} — {s.get('away_team', '')}*{score}\n"
        f"   {market} @ {s.get('odds', '?')} | *{profit_str}*\n"
    )


def save_signal_to_pg(bet: dict) -> int:
    import hashlib
    try:
        import psycopg2
        pg = psycopg2.connect(os.getenv("DATABASE_URL"))
        pg.autocommit = True
        cur = pg.cursor()

        # Stable dedup key — хэш по неизменяемым полям ставки
        uid_src = "|".join(str(bet.get(k) or "") for k in (
            "sport", "home_team", "away_team", "market", "match_date", "odds"
        ))
        signal_uid = hashlib.md5(uid_src.encode()).hexdigest()

        cur.execute("""
            INSERT INTO signals (
                sport, league, home_team, away_team, match_date,
                market, odds, confidence, result, signal_uid, updated_at, created_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,NOW(),NOW())
            ON CONFLICT (signal_uid) DO UPDATE
                SET result    = CASE WHEN signals.result = 'pending'
                                     THEN EXCLUDED.result
                                     ELSE signals.result END,
                    updated_at = NOW()
            RETURNING id
        """, (
            bet.get("sport"), bet.get("league"),
            bet.get("home_team"), bet.get("away_team"),
            bet.get("match_date"), bet.get("market"),
            bet.get("odds"), "medium",
            signal_uid,
        ))
        row = cur.fetchone()
        pg.close()
        return row[0] if row else 0
    except Exception as e:
        print(f"save_signal_to_pg error: {e}")
        return 0


def save_user_signal_view(user_id: int, signal_id: int, watermark_stake: int = 1000):
    if not signal_id:
        return
    try:
        import psycopg2
        pg = psycopg2.connect(os.getenv("DATABASE_URL"))
        pg.autocommit = True
        cur = pg.cursor()
        cur.execute("""
            INSERT INTO user_signal_views (user_id, signal_id, watermark_stake)
            VALUES (%s,%s,%s)
            ON CONFLICT (user_id, signal_id) DO NOTHING
        """, (user_id, signal_id, watermark_stake))
        pg.close()
    except Exception as e:
        print(f"save_user_signal_view error: {e}")


def fmt_new_tennis_signal(s: dict) -> str:
    market_map = {
        "player1_win": f"П1 ({s.get('player1', '')})",
        "player2_win": f"П2 ({s.get('player2', '')})",
    }
    market = market_map.get(s.get("market", ""), s.get("market", ""))
    league = s.get("league", "").split(".")[0].strip()
    date_str = str(s.get("match_date", ""))[:10]
    ev = s.get("ev") or 0
    try:
        ev = float(ev)
        ev_pct = round(ev * 100, 1)
        ev_str = f"{ev_pct:+.1f}%"
    except Exception:
        ev_str = "N/A"
    edge = s.get("edge") or 0
    try:
        edge = float(edge)
        edge_str = f"{edge * 100:.1f}%"
    except Exception:
        edge_str = "N/A"
    stake_pct = s.get("stake_pct") or 0.5
    try:
        stake_pct = float(stake_pct)
        stake_str = f"{stake_pct * 100:.1f}%"
    except Exception:
        stake_str = "0.5%"

    return (
        f"🎾 *{league}*\n"
        f"⚔️ {s.get('player1', '')} — {s.get('player2', '')}\n"
        f"📅 {date_str}\n"
        f"📌 *{market}* @ {s.get('odds_p1') or s.get('odds_p2') or '?'}\n"
        f"📊 EV: {ev_str} | Edge: {edge_str}\n"
        f"💵 Ставка: {stake_str} банка\n"
    )


def fmt_tennis_result(s: dict) -> str:
    result = s.get("result", "")
    res_icon = "✅" if result == "won" else "❌"
    profit = s.get("profit") or 0
    profit_str = f"+{profit:.0f} ₽" if profit > 0 else f"{profit:.0f} ₽"
    market_map = {
        "player1_win": f"П1 ({s.get('player1', '')})",
        "player2_win": f"П2 ({s.get('player2', '')})",
    }
    market = market_map.get(s.get("market", ""), s.get("market", ""))
    return (
        f"{res_icon} 🎾 *{s.get('player1', '')} — {s.get('player2', '')}*\n"
        f"   {market} | *{profit_str}*\n"
    )


def notify_tennis_signals(mode: str = "bets"):
    """Отправить уведомления по теннисным сигналам подписчикам."""
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row

    if mode == "bets":
        rows = conn.execute("""
            SELECT id, match_date, league, player1, player2, player1_eng, player2_eng,
                   surface, odds_p1, odds_p2, market, our_probability, market_probability,
                   ev, edge, kelly, kelly_quarter, stake_pct, confidence, signal_type,
                   confirmed_facts, status, created_at
            FROM tennis_signals
            WHERE status = 'pending'
              AND created_at >= datetime('now', '-24 hours')
            ORDER BY created_at DESC
        """).fetchall()
    elif mode == "results":
        rows = conn.execute("""
            SELECT id, match_date, league, player1, player2, player1_eng, player2_eng,
                   surface, odds_p1, odds_p2, market, our_probability, market_probability,
                   ev, edge, kelly, kelly_quarter, stake_pct, confidence, signal_type,
                   confirmed_facts, status, result, profit, settled_at
            FROM tennis_signals
            WHERE result IN ('won', 'lost')
              AND settled_at IS NOT NULL
              AND settled_at >= datetime('now', '-24 hours')
            ORDER BY settled_at DESC, id DESC
        """).fetchall()
    else:
        rows = []

    conn.close()

    if not rows:
        print(f"Теннисных {'ставок' if mode == 'bets' else 'результатов'} нет")
        return

    signals = [dict(r) for r in rows]
    print(f"Теннисных {'ставок' if mode == 'bets' else 'результатов'}: {len(signals)}")

    subscribers = get_active_subscribers()
    if not subscribers:
        print("Нет активных подписчиков")
        return

    sent = 0
    for user in subscribers:
        tg_id = user["telegram_id"]
        plan = user["plan"]
        user_id = user["id"]
        has_sub = user.get("has_subscription", False)

        new_for_user = []
        for sig in signals:
            key = f"tennis_{mode}_{sig['id']}_u{user_id}"
            if not was_notified("tennis", key):
                new_for_user.append(sig)

        if not new_for_user:
            continue

        if mode == "bets":
            if not has_sub:
                text = (
                    f"🎾 *Новые теннисные сигналы BetAgent*\n\n"
                    f"Алгоритм нашёл *{len(new_for_user)} теннисных value-сигнала(-ов)*.\n\n"
                    f"🔒 Для просмотра нужна подписка.\n\n"
                    f"🎁 Первые 7 дней — *бесплатно* (Basic)\n\n"
                    f"Оформить → /buy"
                )
            elif plan == "basic":
                text = (
                    f"🎾 *Новые теннисные сигналы BetAgent*\n\n"
                    f"Алгоритм нашёл *{len(new_for_user)} теннисных сигнала(-ов)*.\n\n"
                    f"🔵 *Ваш тариф Basic* — показываем ограниченное количество сигналов.\n\n"
                    f"Нажми /signals чтобы увидеть доступные.\n\n"
                    f"🟣 Для доступа ко всем сигналам сразу → /buy"
                )
            else:
                lines = [f"🎾 *Теннисные сигналы — {len(new_for_user)} шт.*\n"]
                for sig in new_for_user[:5]:
                    lines.append(fmt_new_tennis_signal(sig))
                if len(new_for_user) > 5:
                    lines.append(f"_...и ещё {len(new_for_user)-5} сигналов. Смотри /signals_")
                text = "\n".join(lines)
        elif mode == "results":
            wins = sum(1 for b in new_for_user if b.get("result") == "won")
            losses = sum(1 for b in new_for_user if b.get("result") == "lost")
            total_profit = sum(b.get("profit") or 0 for b in new_for_user)
            profit_str = f"+{total_profit:.0f} ₽" if total_profit > 0 else f"{total_profit:.0f} ₽"
            lines = [
                f"🎾 *Теннисные результаты*\n",
                f"✅ {wins} выиграно  ❌ {losses} проиграно  |  *{profit_str}*\n",
            ]
            for sig in new_for_user:
                lines.append(fmt_tennis_result(sig))
            text = "\n".join(lines)

        ok = tg_send(tg_id, text)
        if ok:
            for sig in new_for_user:
                mark_notified("tennis", f"tennis_{mode}_{sig['id']}_u{user_id}", user_id)
            sent += 1
        else:
            log.warning(f"Не удалось отправить теннисное уведомление пользователю {tg_id}")

    print(f"Теннис уведомлено: {sent}/{len(subscribers)}")


def notify_new_bets():
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT b.id, b.market, b.odds, b.ev, b.stake,
               m.sport, m.league, m.home_team, m.away_team, m.match_date
        FROM bets b
        JOIN matches m ON b.match_id = m.id
        WHERE b.result = 'pending'
          AND b.created_at >= datetime('now', '-24 hours')
        ORDER BY b.created_at DESC
    """).fetchall()
    conn.close()

    if not rows:
        print("Новых ставок нет")
        return

    new_bets = [dict(r) for r in rows]
    print(f"Новых ставок: {len(new_bets)}")

    subscribers = get_active_subscribers()
    if not subscribers:
        print("Нет активных подписчиков")
        return

    sent = 0
    for user in subscribers:
        tg_id = user["telegram_id"]
        plan = user["plan"]
        user_id = user["id"]
        has_sub = user.get("has_subscription", False)

        new_for_user = []
        for bet in new_bets:
            key = f"bet_{bet['id']}_u{user_id}"
            if not was_notified("new_bet", key):
                new_for_user.append(bet)

        if not new_for_user:
            continue

        if not has_sub:
            text = (
                f"📡 *Новые сигналы BetAgent*\n\n"
                f"Алгоритм нашёл *{len(new_for_user)} новых value-сигнала(-ов)*.\n\n"
                f"🔒 Для просмотра нужна подписка.\n\n"
                f"🎁 Первые 7 дней — *бесплатно* (Basic)\n\n"
                f"Оформить → /buy"
            )
        elif plan == "basic":
            text = (
                f"📡 *Новые сигналы BetAgent*\n\n"
                f"Алгоритм нашёл *{len(new_for_user)} новых сигнала(-ов)*.\n\n"
                f"🔵 *Ваш тариф Basic* — показываем ограниченное количество сигналов.\n\n"
                f"Нажми /signals чтобы увидеть доступные.\n\n"
                f"🟣 Для доступа ко всем сигналам сразу → /buy"
            )
        else:
            lines = [f"📡 *Новые сигналы — {len(new_for_user)} шт.*\n"]
            for bet in new_for_user[:5]:
                lines.append(fmt_new_signal(bet))
            if len(new_for_user) > 5:
                lines.append(f"_...и ещё {len(new_for_user)-5} сигналов. Смотри /signals_")
            text = "\n".join(lines)

        # ВАЖНО: логика тарифов и истории сигналов
        if plan not in ("basic",) and has_sub:
            for bet in new_for_user:
                sig_id = save_signal_to_pg(bet)
                if sig_id:
                    save_user_signal_view(user_id, sig_id)
        elif plan == "basic" and has_sub:
            for bet in new_for_user[:5]:
                sig_id = save_signal_to_pg(bet)
                if sig_id:
                    save_user_signal_view(user_id, sig_id)

        ok = tg_send(tg_id, text)
        if ok:
            for bet in new_for_user:
                mark_notified("new_bet", f"bet_{bet['id']}_u{user_id}", user_id)
            sent += 1
        else:
            log.warning(f"Не удалось отправить пользователю {tg_id}")

    print(f"Уведомлено пользователей: {sent}/{len(subscribers)}")


def _has_bets_settled_at(conn: sqlite3.Connection) -> bool:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(bets)").fetchall()]
    return "settled_at" in cols


def notify_results():
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row

    if _has_bets_settled_at(conn):
        rows = conn.execute("""
            SELECT b.id, b.market, b.odds, b.profit, b.result, b.settled_at,
                   m.sport, m.league, m.home_team, m.away_team,
                   m.match_date, m.home_score, m.away_score
            FROM bets b
            JOIN matches m ON b.match_id = m.id
            WHERE b.result IN ('won', 'lost')
              AND COALESCE(b.excluded_from_stats,0)=0
              AND b.settled_at IS NOT NULL
              AND b.settled_at >= datetime('now', '-24 hours')
            ORDER BY b.settled_at DESC, b.id DESC
        """).fetchall()
    else:
        # Без settled_at лучше не слать "результаты за сегодня" по matches.updated_at,
        # иначе старые закрытые ставки будут переотправляться после репарсинга матчей.
        print("SKIP results notify: в bets нет поля settled_at")
        conn.close()
        return

    conn.close()

    if not rows:
        print("Новых результатов нет")
        return

    closed = [dict(r) for r in rows]
    print(f"Закрытых ставок: {len(closed)}")

    subscribers = get_active_subscribers()
    if not subscribers:
        print("Нет активных подписчиков")
        return

    sent = 0
    for user in subscribers:
        tg_id = user["telegram_id"]
        user_id = user["id"]

        new_results = []
        for bet in closed:
            key = f"result_{bet['id']}_u{user_id}"
            if not was_notified("result", key):
                new_results.append(bet)

        if not new_results:
            continue

        wins = sum(1 for b in new_results if b["result"] == "won")
        losses = sum(1 for b in new_results if b["result"] == "lost")
        total_profit = sum(b.get("profit") or 0 for b in new_results)
        profit_str = f"+{total_profit:.0f} ₽" if total_profit > 0 else f"{total_profit:.0f} ₽"

        lines = [
            f"📋 *Результаты BetAgent*\n",
            f"✅ {wins} выиграно  ❌ {losses} проиграно  |  *{profit_str}*\n",
        ]
        for bet in new_results:
            lines.append(fmt_result(bet))

        text = "\n".join(lines)

        ok = tg_send(tg_id, text)
        if ok:
            for bet in new_results:
                mark_notified("result", f"result_{bet['id']}_u{user_id}", user_id)
            sent += 1
        else:
            log.warning(f"Не удалось отправить результаты пользователю {tg_id}")

    print(f"Уведомлено пользователей: {sent}/{len(subscribers)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["bets", "results"], required=True)
    parser.add_argument("--tennis", action="store_true", help="Notify tennis signals instead of bets")
    args = parser.parse_args()

    if args.tennis:
        notify_tennis_signals(mode=args.mode)
    elif args.mode == "bets":
        notify_new_bets()
    elif args.mode == "results":
        notify_results()


if __name__ == "__main__":
    main()
