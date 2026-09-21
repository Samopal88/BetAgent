#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified notification layer — minimal skeleton.

Provides:
- Unified dedup table (notification_log)
- was_sent() / mark_sent() helpers
- Thin send wrappers: send_admin(), send_client(), send_channel()

Does NOT refactor existing endpoints yet — just infrastructure.
"""

import os
import sqlite3
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = os.getenv("BETAGENT_DB", str(Path(__file__).parent / "betagent.db"))

# Telegram HTML message limit is 4096 chars. Keep batches small.
MAX_ADMIN_BETS_PER_MSG = 15
MAX_CHANNEL_BETS_PER_MSG = 5


# ── Canonical event types ──────────────────────────────────────────

class EventType:
    NEW_BET = "NEW_BET"
    SETTLED_RESULT = "SETTLED_RESULT"
    WEEKLY_REPORT = "WEEKLY_REPORT"
    MONTHLY_REPORT = "MONTHLY_REPORT"
    SYSTEM_ALERT = "SYSTEM_ALERT"


# ── Dataclass ──────────────────────────────────────────────────────

@dataclass
class NotificationEvent:
    event_type: str       # NEW_BET, SETTLED_RESULT, etc.
    entity_id: str        # bet_id, weekly_2026_15, etc.
    target: str           # admin, client, channel
    data: dict            # sport, teams, market, odds, etc.

    @property
    def notify_key(self) -> str:
        return f"{self.event_type}:{self.entity_id}:{self.target}"


# ── Schema ─────────────────────────────────────────────────────────

def ensure_schema():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            target TEXT NOT NULL,
            notify_key TEXT NOT NULL UNIQUE,
            sent_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


# ── Dedup helpers ──────────────────────────────────────────────────

def was_sent(event_type: str, entity_id: str, target: str) -> bool:
    key = f"{event_type}:{entity_id}:{target}"
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT 1 FROM notification_log WHERE notify_key = ?", (key,)
    ).fetchone()
    conn.close()
    return row is not None


def mark_sent(event_type: str, entity_id: str, target: str):
    key = f"{event_type}:{entity_id}:{target}"
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR IGNORE INTO notification_log (event_type, entity_id, target, notify_key, sent_at) VALUES (?, ?, ?, ?, ?)",
        (event_type, entity_id, target, key, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()


# ── Thin send wrappers ─────────────────────────────────────────────

def _get_admin_token():
    return os.getenv("TELEGRAM_BOT_TOKEN", "")

def _get_admin_chat():
    return os.getenv("TELEGRAM_CHAT_ID", "")

def _get_client_token():
    return os.getenv("CLIENT_BOT_TOKEN", "")

def _get_channel_token():
    return os.getenv("CHANNEL_BOT_TOKEN", "")

def _get_channel_id():
    return os.getenv("CHANNEL_ID", "")


def send_admin(text: str) -> bool:
    """Send message to admin chat via TELEGRAM_BOT_TOKEN."""
    token = _get_admin_token()
    chat_id = _get_admin_chat()
    if not token or not chat_id:
        print("[notification_layer] Admin token/chat_id not configured")
        return False
    try:
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if r.status_code == 200:
            print("[notification_layer] Admin message sent")
            return True
        print(f"[notification_layer] Admin send failed: {r.status_code} {r.text[:200]}")
        return False
    except Exception as e:
        print(f"[notification_layer] Admin send error: {e}")
        return False


def send_client(text: str, telegram_id: str) -> bool:
    """Send message to individual subscriber via CLIENT_BOT_TOKEN."""
    token = _get_client_token()
    if not token or not telegram_id:
        return False
    try:
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": telegram_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def send_channel(text: str) -> bool:
    """Send message to Telegram channel via CHANNEL_BOT_TOKEN."""
    token = _get_channel_token()
    channel_id = _get_channel_id()
    if not token or not channel_id:
        print("[notification_layer] Channel token/id not configured")
        return False
    try:
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": channel_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        )
        if r.status_code == 200:
            print("[notification_layer] Channel message sent")
            return True
        print(f"[notification_layer] Channel send failed: {r.status_code} {r.text[:200]}")
        return False
    except Exception as e:
        print(f"[notification_layer] Channel send error: {e}")
        return False


# ── Convenience: send with dedup ───────────────────────────────────

def send_with_dedup(event: NotificationEvent, text: str) -> bool:
    """Check dedup, send if new, mark as sent."""
    if was_sent(event.event_type, event.entity_id, event.target):
        print(f"[notification_layer] Already sent: {event.notify_key}")
        return False

    target_map = {
        "admin": lambda: send_admin(text),
        "channel": lambda: send_channel(text),
    }

    sender = target_map.get(event.target)
    if sender is None:
        print(f"[notification_layer] Unknown target: {event.target}")
        return False

    ok = sender()
    if ok:
        mark_sent(event.event_type, event.entity_id, event.target)
    return ok


# ── NEW_BET: unified dispatcher ────────────────────────────────────

def _fmt_sport(sport):
    return {"hockey": "🏒", "football": "⚽", "tennis": "🎾"}.get(sport, "🎯")


def _fmt_market(label, home_team=None, away_team=None):
    mapping = {
        "П1": "🏠П1", "П2": "✈️П2", "X": "🤝X",
        "home": "🏠П1", "away": "✈️П2", "draw": "🤝X",
        "btts_yes": "⚽⚽ОЗ да", "btts_no": "⛔ОЗ нет",
        "ОЗ да": "⚽⚽ОЗ да", "ОЗ нет": "⛔ОЗ нет",
        "over_2_5": "📈ТБ 2.5", "under_2_5": "📉ТМ 2.5",
        "over_1_5": "📈ТБ 1.5", "under_1_5": "📉ТМ 1.5",
        "player1_win": f"🎾П1 ({home_team or ''})",
        "player2_win": f"🎾П2 ({away_team or ''})",
    }
    return mapping.get(label, label or "?")


def _league_display(league):
    if not league:
        return "—"
    import re
    league = re.sub(r'\.?\s*[Сс]езон\s*\d{2}/\d{2}', '', league).strip()
    parts = [p.strip() for p in league.split('.') if p.strip()]
    if len(parts) >= 2:
        league = parts[-1]
    for sep in [" | ", " - "]:
        if sep in league:
            league = league.split(sep)[0].strip()
    return league


def _format_admin_bet_card(bet: dict) -> str:
    """Format a single bet for admin channel — matches tg_bot.py style."""
    ev_pct = (bet.get("ev") or 0) * 100
    stake = bet.get("stake") or 0
    date_str = str(bet.get("match_date", ""))[5:16]
    market_display = _fmt_market(bet["market"], bet.get("home_team"), bet.get("away_team"))
    ev_icon = "🔥" if ev_pct >= 20 else ("✅" if ev_pct >= 10 else "⚡")
    bookmaker = str(bet.get("bookmaker", "fonbet")).upper()
    signal_type = bet.get("signal_type", "")
    rule = bet.get("rule", "")
    strategy = _fmt_strategy(rule, signal_type)

    return (
        f"{_fmt_sport(bet['sport'])} <b>{bet['home_team']} — {bet['away_team']}</b>\n"
        f"   📅 {date_str} | {market_display} @ <b>{bet['odds']}</b> | БК: <b>{bookmaker}</b>\n"
        f"   📋 {strategy}\n"
        f"   💰 {stake:,.0f} руб | {ev_icon} EV: {ev_pct:.1f}%"
    )


def _fmt_strategy(rule, signal_type):
    if rule:
        labels = {
            "BTTS_YES_CORE": "⚽⚽ Оба забьют",
            "DRAW_SA": "🤝 Ничья SerieA",
            "DRAW_BL1_FL1": "🤝 Ничья Бундеслига/Лига1",
            "DRAW_BALANCED_LINE_SA": "🤝 Ничья равная SerieA",
            "AWAY_SA_STRICT_PLUS": "✈️ Гость SerieA",
            "RPL_OVER25_BTTS": "⚽ ТБ 2.5 РПЛ (двойной сигнал)",
            "PD_BTTS_DOUBLE": "⚽⚽ Оба забьют Ла Лига (двойной сигнал)",
        }
        return labels.get(rule, rule)
    conf = {"High": "🔥 Высокая", "Medium": "⚡ Средняя", "Low": "💤 Низкая"}.get(signal_type, signal_type or "")
    return conf


def _format_channel_bet_card(bet: dict) -> str:
    """Format a single bet for public channel — matches content_publisher.py style."""
    sport = bet.get("sport") or ""
    if sport and "tennis" in sport.lower():
        date_str = str(bet.get("match_date", ""))[:10]
        surface = (bet.get("surface") or "").strip()
        lines = [
            "🎾 tennis",
        ]
        if surface:
            lines.append(f"🏟️ {surface}")
        lines.extend([
            f"⚔️ {bet.get('home_team', '?')} — {bet.get('away_team', '?')}",
            f"📅 {date_str}",
        ])
        return "\n".join(lines)
    else:
        return (
            f"{_fmt_sport(sport)} {_league_display(bet.get('league'))}\n"
            f"⚔️ {bet.get('home_team', '?')} — {bet.get('away_team', '?')}\n"
            f"📅 {str(bet.get('match_date', ''))[:10]}"
        )


def notify_new_bet_unified(
    admin: bool = True,
    channel: bool = True,
    admin_days: int = 30,
    channel_hours: int = 2,
):
    """
    Unified NEW_BET dispatcher.

    Queries pending bets, formats them, sends to admin and/or channel
    via notification_layer with unified dedup.

    Returns dict with counts per target.
    """
    ensure_schema()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Query for admin (last N days)
    admin_since = (datetime.now() - timedelta(days=admin_days)).strftime("%Y-%m-%d %H:%M:%S")
    admin_rows = conn.execute("""
        SELECT b.id as bet_id, b.market, b.odds, b.stake, b.ev, b.signal_type,
               b.rule, b.reasons,
               COALESCE(b.recommended_bookmaker, 'fonbet') as bookmaker,
               m.sport, m.league, m.home_team, m.away_team, m.match_date
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result = 'pending'
          AND b.created_at >= ?
        ORDER BY m.match_date ASC
    """, (admin_since,)).fetchall()

    # Query for channel (last N hours — shorter window for public)
    channel_since = (datetime.now() - timedelta(hours=channel_hours)).strftime("%Y-%m-%d %H:%M:%S")
    channel_rows = conn.execute("""
        SELECT b.id as bet_id, b.market, b.odds, b.ev,
               ts.surface as surface,
               m.sport, m.league, m.home_team, m.away_team, m.match_date
        FROM bets b
        JOIN matches m ON b.match_id = m.id
        LEFT JOIN (
            SELECT bet_id, MAX(surface) AS surface
            FROM tennis_signals
            GROUP BY bet_id
        ) ts ON ts.bet_id = b.id
        WHERE b.result = 'pending'
          AND b.created_at >= ?
        ORDER BY b.created_at ASC
    """, (channel_since,)).fetchall()

    conn.close()

    results = {"admin_sent": 0, "channel_sent": 0, "admin_skipped": 0, "channel_skipped": 0}

    # ── Admin path ─────────────────────────────────────────────
    if admin and admin_rows:
        admin_bets = [dict(r) for r in admin_rows]
        # Split tennis and non-tennis (matching tg_bot.py behavior)
        tennis_bets = [b for b in admin_bets if b.get("sport") == "tennis"]
        other_bets = [b for b in admin_bets if b.get("sport") != "tennis"]

        # Tennis bets
        tennis_unsent = []
        for b in tennis_bets:
            if not was_sent(EventType.NEW_BET, f"tennis:{b['bet_id']}", "admin"):
                tennis_unsent.append(b)

        if tennis_unsent:
            # Split into chunks to avoid Telegram 4096 char limit
            for i in range(0, len(tennis_unsent), MAX_ADMIN_BETS_PER_MSG):
                chunk = tennis_unsent[i:i + MAX_ADMIN_BETS_PER_MSG]
                lines = [f"🎾 <b>Теннисные прогнозы — {len(chunk)} шт.</b>\n"]
                for b in chunk:
                    ev_pct = (b.get("ev") or 0) * 100
                    stake = b.get("stake") or 0
                    date_str = str(b.get("match_date", ""))[:10]
                    market_display = _fmt_market(b["market"], b.get("home_team"), b.get("away_team"))
                    ev_icon = "🔥" if ev_pct >= 20 else ("✅" if ev_pct >= 10 else "⚡")
                    lines.append(
                        f"🎾 <b>{b['home_team']} — {b['away_team']}</b>\n"
                        f"   📅 {date_str} | {market_display} @ <b>{b['odds']}</b>\n"
                        f"   💰 {stake:,.0f} руб | {ev_icon} EV: {ev_pct:.1f}%"
                    )
                text = "\n".join(lines)
                evt = NotificationEvent(EventType.NEW_BET, f"tennis_batch_{datetime.now().strftime('%Y%m%d_%H')}_{i}", "admin", {})
                if send_with_dedup(evt, text):
                    for b in chunk:
                        mark_sent(EventType.NEW_BET, f"tennis:{b['bet_id']}", "admin")
                    results["admin_sent"] += len(chunk)
                else:
                    results["admin_skipped"] += len(chunk)

        # Other sports bets
        other_unsent = []
        for b in other_bets:
            if not was_sent(EventType.NEW_BET, str(b["bet_id"]), "admin"):
                other_unsent.append(b)

        if other_unsent:
            # Split into chunks to avoid Telegram 4096 char limit
            for i in range(0, len(other_unsent), MAX_ADMIN_BETS_PER_MSG):
                chunk = other_unsent[i:i + MAX_ADMIN_BETS_PER_MSG]
                lines = [f"🎯 <b>Новые прогнозы — {len(chunk)} шт.</b>\n"]
                for b in chunk:
                    lines.append(_format_admin_bet_card(b))
                text = "\n".join(lines)
                evt = NotificationEvent(EventType.NEW_BET, f"batch_{datetime.now().strftime('%Y%m%d_%H')}_{i}", "admin", {})
                if send_with_dedup(evt, text):
                    for b in chunk:
                        mark_sent(EventType.NEW_BET, str(b["bet_id"]), "admin")
                    results["admin_sent"] += len(chunk)
                else:
                    results["admin_skipped"] += len(chunk)

    # ── Channel path ───────────────────────────────────────────
    if channel and channel_rows:
        channel_bets = [dict(r) for r in channel_rows]
        unsent = []
        for b in channel_bets:
            if not was_sent(EventType.NEW_BET, str(b["bet_id"]), "channel"):
                unsent.append(b)

        if unsent:
            # Group tennis and non-tennis for channel
            tennis = [b for b in unsent if (b.get("sport") or "").startswith("tennis")]
            others = [b for b in unsent if not (b.get("sport") or "").startswith("tennis")]

            for group, header in [(tennis, "🎾 Теннис"), (others, "⚡️ <b>НОВАЯ РЕКОМЕНДАЦИЯ</b>")]:
                if not group:
                    continue
                lines = [f"{header}\n"]
                for b in group:
                    lines.append(_format_channel_bet_card(b))
                if header == "🎾 Теннис":
                    lines.append("\nПолные параметры и сторона ставки — в боте → @betagent_analytics_bot")
                else:
                    lines.append("\nПолные параметры — подписчикам бота.\n→ @betagent_analytics_bot")
                text = "\n".join(lines)
                evt = NotificationEvent(EventType.NEW_BET, str(group[0]["bet_id"]), "channel", {})
                if send_with_dedup(evt, text):
                    for b in group:
                        mark_sent(EventType.NEW_BET, str(b["bet_id"]), "channel")
                    results["channel_sent"] += len(group)
                else:
                    results["channel_skipped"] += len(group)

    return results


# ── SETTLED_RESULT: unified dispatcher ─────────────────────────────

def _format_admin_result_card(bet: dict) -> str:
    """Format a single settled bet for admin — matches tg_bot.py style."""
    profit = bet.get("profit") or 0
    score = f" {bet.get('home_score', '')}:{bet.get('away_score', '')}" if bet.get("home_score") is not None else ""
    won = bet.get("result") == "won"
    icon = "✅" if won else "❌"
    return (
        f"{icon} {_fmt_sport(bet['sport'])} {bet['home_team']} — {bet['away_team']}{score} | "
        f"{_fmt_market(bet['market'])} @ {bet['odds']} | {profit:+,.0f} руб"
    )


def _format_channel_result_card(bet: dict, roi: float) -> str:
    """Format a single settled bet for channel — matches content_publisher.py style."""
    won = bet.get("result") == "won"
    sport = bet.get("sport") or ""
    league = _league_display(bet.get("league"))
    text = (
        f"{'✅' if won else '❌'} <b>РЕЗУЛЬТАТ</b>\n\n"
        f"{_fmt_sport(sport)} {league} — "
        f"<b>{'сработало' if won else 'не сработало'}</b>\n"
    )
    if won:
        text += "Алгоритм работает. Статистика обновлена."
    else:
        text += f"Отрицательный результат — часть любой математической системы.\nДистанция решает. Текущий ROI: {roi:+.2f}%"
    text += "\n\n→ @betagent_analytics_bot"
    return text


def notify_settled_results_unified(
    admin: bool = True,
    channel: bool = True,
    admin_days: int = 2,
    channel_hours: int = 4,
):
    """
    Unified SETTLED_RESULT dispatcher.

    Queries recently settled bets (won/lost), formats them, sends to
    admin and/or channel via notification_layer with unified dedup.

    Returns dict with counts per target.
    """
    ensure_schema()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # ── Admin query: last N days (matches tg_bot.py get_closed_bets) ──
    admin_since = (datetime.now() - timedelta(days=admin_days)).strftime("%Y-%m-%d")
    admin_rows = conn.execute("""
        SELECT b.id as bet_id, b.result, b.market, b.odds, b.stake, b.profit,
               m.sport, m.home_team, m.away_team, m.home_score, m.away_score
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result IN ('won','lost')
          AND m.updated_at >= ?
        ORDER BY m.updated_at DESC
        LIMIT 50
    """, (admin_since,)).fetchall()

    # ── Channel query: last N hours (matches content_publisher.py) ──
    channel_since = (datetime.now() - timedelta(hours=channel_hours)).strftime("%Y-%m-%d %H:%M:%S")
    channel_rows = conn.execute("""
        SELECT b.id, b.odds, b.result, b.created_at, m.sport, m.league
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result IN ('won','lost') AND COALESCE(b.excluded_from_stats,0)=0 AND b.created_at >= ?
        ORDER BY b.created_at ASC
    """, (channel_since,)).fetchall()

    # All-time ROI for channel (matches content_publisher.py behavior)
    stats = conn.execute("""
        SELECT COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN stake ELSE 0 END),0) AS staked,
               COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN profit ELSE 0 END),0) AS profit
        FROM bets WHERE COALESCE(excluded_from_stats,0)=0
    """).fetchone()
    conn.close()
    roi = (stats["profit"] / stats["staked"] * 100) if stats["staked"] else 0

    results = {"admin_sent": 0, "channel_sent": 0, "admin_skipped": 0, "channel_skipped": 0}

    # ── Admin path ─────────────────────────────────────────────
    if admin and admin_rows:
        admin_bets = [dict(r) for r in admin_rows]
        unsent = []
        for b in admin_bets:
            sent_key = f"{b['bet_id']}:{b['result']}"
            if not was_sent(EventType.SETTLED_RESULT, sent_key, "admin"):
                unsent.append((b, sent_key))

        if unsent:
            wins = sum(1 for b, _ in unsent if b["result"] == "won")
            losses = sum(1 for b, _ in unsent if b["result"] == "lost")
            total_profit = sum((b.get("profit") or 0) for b, _ in unsent)
            lines = [f"📋 <b>Результаты — W:{wins} L:{losses} | {total_profit:+,.0f} руб</b>\n"]
            for b, sent_key in unsent:
                lines.append(_format_admin_result_card(b))
            text = "\n".join(lines)
            evt = NotificationEvent(EventType.SETTLED_RESULT, f"batch_{datetime.now().strftime('%Y%m%d_%H')}", "admin", {})
            if send_with_dedup(evt, text):
                for b, sent_key in unsent:
                    mark_sent(EventType.SETTLED_RESULT, sent_key, "admin")
                results["admin_sent"] += len(unsent)
            else:
                results["admin_skipped"] += len(unsent)

    # ── Channel path ───────────────────────────────────────────
    if channel and channel_rows:
        channel_bets = [dict(r) for r in channel_rows]
        for b in channel_bets:
            if not was_sent(EventType.SETTLED_RESULT, str(b["id"]), "channel"):
                won = b["result"] == "won"
                text = _format_channel_result_card(b, roi)
                evt = NotificationEvent(EventType.SETTLED_RESULT, str(b["id"]), "channel", {})
                if send_with_dedup(evt, text):
                    results["channel_sent"] += 1
                else:
                    results["channel_skipped"] += 1

    return results


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="Run self-test")
    ap.add_argument("--dry-run", action="store_true", help="Query bets but don't send")
    ap.add_argument("--admin-days", type=int, default=30)
    ap.add_argument("--channel-hours", type=int, default=2)
    args = ap.parse_args()

    if args.test:
        ensure_schema()
        import tempfile
        old_db = DB_PATH
        test_db = tempfile.mktemp(suffix=".db")
        import notification_layer as nl
        nl.DB_PATH = test_db
        nl.ensure_schema()

        assert not nl.was_sent("WEEKLY_REPORT", "2026_15", "channel")
        nl.mark_sent("WEEKLY_REPORT", "2026_15", "channel")
        assert nl.was_sent("WEEKLY_REPORT", "2026_15", "channel")

        evt = NotificationEvent("WEEKLY_REPORT", "2026_15", "channel", {})
        assert evt.notify_key == "WEEKLY_REPORT:2026_15:channel"

        nl.DB_PATH = old_db
        print("Self-test passed")
    elif args.dry_run:
        ensure_schema()
        results = notify_new_bet_unified(
            admin=False, channel=False,
            admin_days=args.admin_days,
            channel_hours=args.channel_hours,
        )
        print(f"Dry run: {results}")
    else:
        ensure_schema()
        results = notify_new_bet_unified(
            admin_days=args.admin_days,
            channel_hours=args.channel_hours,
        )
        print(f"Results: {results}")
