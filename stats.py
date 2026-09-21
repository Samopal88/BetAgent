#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — stats.py

Полная статистика системы:
- Банкролл и история
- ROI по видам спорта и лигам
- Серии побед/поражений
- Лучшие и худшие ставки
- Калибровка (насколько наши вероятности точны)

Запуск: python stats.py
        python stats.py --days 7
        python stats.py --sport hockey
"""

import os, sqlite3, argparse
from datetime import datetime, timedelta
from pathlib import Path

DB = Path(os.getenv("BETAGENT_DB", "betagent.db"))

def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def bar(value, max_val, width=20, char="█"):
    if max_val == 0:
        return " " * width
    filled = int(width * value / max_val)
    return char * filled + "░" * (width - filled)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days",  type=int, default=30)
    ap.add_argument("--sport", default=None)
    args = ap.parse_args()

    conn = get_conn()
    since = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    sport_filter = "AND m.sport = ?" if args.sport else ""
    sport_params = [args.sport] if args.sport else []

    print(f"\n{'='*60}")
    print(f"  BETAGENT — СТАТИСТИКА")
    print(f"  {datetime.now().strftime('%d.%m.%Y %H:%M')} | период: {args.days} дней")
    print(f"{'='*60}")

    # ── БАНКРОЛЛ ──────────────────────────────────────────────
    bank = float(os.getenv("BETAGENT_BANK", "100000"))
    total_profit = conn.execute("""
        SELECT COALESCE(SUM(b.profit), 0) as p
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result IN ('won','lost') AND b.created_at >= ?
    """, (since,)).fetchone()["p"]

    current_bank = bank + total_profit
    print(f"\n💰 БАНКРОЛЛ")
    print(f"  Стартовый:  {bank:>10,.0f} руб")
    print(f"  Прибыль:    {total_profit:>+10,.0f} руб")
    print(f"  Текущий:    {current_bank:>10,.0f} руб")
    roi_pct = total_profit / bank * 100 if bank else 0
    status = "✅" if roi_pct >= 4 else ("⚠️" if roi_pct >= 0 else "❌")
    print(f"  ROI:        {roi_pct:>+9.2f}%  {status}  (цель: +4%)")

    # ── ОБЩАЯ СТАТИСТИКА ──────────────────────────────────────
    stats = conn.execute(f"""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN b.result='won'     THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN b.result='lost'    THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN b.result='pending' THEN 1 ELSE 0 END) as pending,
            COALESCE(SUM(CASE WHEN b.result IN ('won','lost') THEN b.stake ELSE 0 END), 0) as staked,
            COALESCE(SUM(CASE WHEN b.result IN ('won','lost') THEN b.profit ELSE 0 END), 0) as profit
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.created_at >= ? {sport_filter}
    """, [since] + sport_params).fetchone()

    closed = stats["wins"] + stats["losses"]
    winrate = stats["wins"] / closed * 100 if closed > 0 else 0
    roi = stats["profit"] / stats["staked"] * 100 if stats["staked"] > 0 else 0

    print(f"\n📊 СТАВКИ (последние {args.days} дней)")
    print(f"  Всего:      {stats['total']}")
    print(f"  Закрытых:   {closed}  (W:{stats['wins']} L:{stats['losses']})")
    print(f"  Активных:   {stats['pending']}")
    print(f"  Поставлено: {stats['staked']:,.0f} руб")
    print(f"  Прибыль:    {stats['profit']:+,.0f} руб")
    if closed > 0:
        print(f"  Винрейт:    {winrate:.1f}%  {bar(winrate, 100, 15)}")
        print(f"  ROI:        {roi:+.2f}%")

    # ── ПО ВИДАМ СПОРТА ───────────────────────────────────────
    by_sport = conn.execute(f"""
        SELECT m.sport,
            COUNT(*) as total,
            SUM(CASE WHEN b.result='won' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN b.result='lost' THEN 1 ELSE 0 END) as losses,
            COALESCE(SUM(CASE WHEN b.result IN ('won','lost') THEN b.stake ELSE 0 END), 0) as staked,
            COALESCE(SUM(CASE WHEN b.result IN ('won','lost') THEN b.profit ELSE 0 END), 0) as profit
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result IN ('won','lost') AND b.created_at >= ?
        GROUP BY m.sport
    """, (since,)).fetchall()

    if by_sport:
        print(f"\n🏆 ПО ВИДАМ СПОРТА")
        for s in by_sport:
            cl = s["wins"] + s["losses"]
            wr = s["wins"] / cl * 100 if cl > 0 else 0
            roi_s = s["profit"] / s["staked"] * 100 if s["staked"] > 0 else 0
            emoji = "🏒" if s["sport"] == "hockey" else "⚽"
            print(f"  {emoji} {s['sport']:10s} | {cl:3d} ставок | "
                  f"W:{s['wins']} L:{s['losses']} | "
                  f"ROI: {roi_s:+.1f}% | "
                  f"прибыль: {s['profit']:+,.0f} руб")

    # ── ПО ЛИГАМ ──────────────────────────────────────────────
    by_league = conn.execute(f"""
        SELECT m.league,
            COUNT(*) as total,
            SUM(CASE WHEN b.result='won' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN b.result='lost' THEN 1 ELSE 0 END) as losses,
            COALESCE(SUM(CASE WHEN b.result IN ('won','lost') THEN b.profit ELSE 0 END), 0) as profit
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result IN ('won','lost') AND b.created_at >= ? {sport_filter}
        GROUP BY m.league
        ORDER BY profit DESC
    """, [since] + sport_params).fetchall()

    if by_league:
        print(f"\n🗺  ПО ЛИГАМ")
        for l in by_league:
            cl = l["wins"] + l["losses"]
            wr = l["wins"] / cl * 100 if cl > 0 else 0
            league_short = l["league"][:35]
            print(f"  {league_short:35s} | {cl:2d} | W:{l['wins']} L:{l['losses']} | {l['profit']:+,.0f} руб")

    # ── АКТИВНЫЕ СТАВКИ ───────────────────────────────────────
    pending = conn.execute(f"""
        SELECT b.id, m.sport, m.home_team, m.away_team, m.match_date,
               b.market, b.odds, b.stake, b.ev, b.our_probability,
               b.signal_type
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result = 'pending'
        ORDER BY m.match_date ASC
    """).fetchall()

    if pending:
        print(f"\n⏳ АКТИВНЫЕ СТАВКИ: {len(pending)}")
        for b in pending:
            emoji = "🏒" if b["sport"] == "hockey" else "⚽"
            date_str = b["match_date"][:16] if b["match_date"] else "?"
            print(f"  {emoji} {date_str} | {b['home_team']} — {b['away_team']}")
            print(f"     {({'home':'🏠П1','away':'✈️П2','draw':'🤝X'}.get(b['market'], b['market']))} @ {b['odds']} | "
                  f"Ставка: {b['stake']:,.0f} руб | "
                  f"EV: {b['ev']:.1%} | "
                  f"Наша P: {b['our_probability']:.0%} | "
                  f"{b['signal_type']}")

    # ── ПОСЛЕДНИЕ 10 ЗАКРЫТЫХ ─────────────────────────────────
    last = conn.execute(f"""
        SELECT b.result, m.sport, m.home_team, m.away_team, m.match_date,
               b.market, b.odds, b.stake, b.profit, b.our_probability
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result IN ('won','lost') AND b.created_at >= ? {sport_filter}
        ORDER BY b.created_at DESC
        LIMIT 10
    """, [since] + sport_params).fetchall()

    if last:
        print(f"\n📋 ПОСЛЕДНИЕ ЗАКРЫТЫЕ СТАВКИ")
        for b in last:
            icon = "✅" if b["result"] == "won" else "❌"
            emoji = "🏒" if b["sport"] == "hockey" else "⚽"
            date_str = b["match_date"][:10] if b["match_date"] else "?"
            print(f"  {icon} {emoji} {date_str} | "
                  f"{b['home_team']} — {b['away_team']} | "
                  f"{({'home':'🏠П1','away':'✈️П2','draw':'🤝X'}.get(b['market'], b['market']))} @ {b['odds']} | "
                  f"{b['profit']:+,.0f} руб")

    # ── СЕРИЯ ─────────────────────────────────────────────────
    recent = conn.execute("""
        SELECT b.result FROM bets b
        JOIN matches m ON b.match_id = m.id
        WHERE b.result IN ('won','lost')
        ORDER BY b.created_at DESC LIMIT 20
    """).fetchall()

    if recent:
        streak = 0
        streak_type = recent[0]["result"]
        for r in recent:
            if r["result"] == streak_type:
                streak += 1
            else:
                break
        icon = "🔥" if streak_type == "won" else "❄️"
        print(f"\n{icon} ТЕКУЩАЯ СЕРИЯ: {streak}x {streak_type.upper()}")

    # ── ЦЕЛЬ ROI ──────────────────────────────────────────────
    print(f"\n{'='*60}")
    needed = 4.0 - roi_pct
    if roi_pct >= 4:
        print(f"  ✅ ЦЕЛЬ ROI > 4% ДОСТИГНУТА! Текущий ROI: {roi_pct:.2f}%")
    elif roi_pct >= 0:
        print(f"  ⚠️  До цели ROI 4%: ещё {needed:.1f}% | Текущий: {roi_pct:.2f}%")
    else:
        print(f"  ❌ ROI отрицательный: {roi_pct:.2f}% | Нужно: +{abs(roi_pct)+4:.1f}%")
    print(f"{'='*60}\n")

    conn.close()

if __name__ == "__main__":
    main()
