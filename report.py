#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — report.py

Показывает текущее состояние системы:
- активные ставки
- результаты закрытых ставок
- ROI
- последние прогоны

Запуск: python report.py
"""

import os, sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB = Path(os.getenv("BETAGENT_DB", "betagent.db"))

def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def main():
    conn = get_conn()
    now = datetime.now()
    print(f"\n{'='*60}")
    print(f"📊 BETAGENT ОТЧЁТ — {now.strftime('%d.%m.%Y %H:%M')}")
    print(f"{'='*60}")

    # Активные ставки
    pending = conn.execute("""
        SELECT b.id, m.sport, m.home_team, m.away_team,
               m.match_date, b.market, b.odds, b.stake, b.ev
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result = 'pending'
        ORDER BY m.match_date ASC
    """).fetchall()

    print(f"\n🎯 АКТИВНЫЕ СТАВКИ: {len(pending)}")
    for b in pending:
        market_label = {"home": "П1", "draw": "X", "away": "П2"}.get(b["market"], b["market"])
        print(f"  [{b['sport'][:4]}] {b['home_team']} — {b['away_team']}")
        print(f"  {b['match_date'][:16]} | {market_label} @ {b['odds']} | "
              f"Ставка: {b['stake']:.0f} руб | EV: {b['ev']:.1%}")

    # Статистика за месяц
    month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    stats = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN result='won' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN result='lost' THEN 1 ELSE 0 END) as losses,
            SUM(COALESCE(profit, 0)) as total_profit,
            SUM(COALESCE(stake, 0)) as total_staked
        FROM bets b
        JOIN matches m ON b.match_id = m.id
        WHERE b.result IN ('won', 'lost')
          AND COALESCE(b.excluded_from_stats, 0) = 0
          AND b.created_at >= ?
    """, (month_ago,)).fetchone()

    print(f"\n📈 СТАТИСТИКА (30 дней):")
    if stats["total"] > 0:
        roi = stats["total_profit"] / stats["total_staked"] * 100 if stats["total_staked"] else 0
        winrate = stats["wins"] / stats["total"] * 100
        print(f"  Всего ставок: {stats['total']} | W: {stats['wins']} L: {stats['losses']}")
        print(f"  Винрейт: {winrate:.1f}%")
        print(f"  Поставлено: {stats['total_staked']:.0f} руб")
        print(f"  Прибыль: {stats['total_profit']:+.0f} руб")
        print(f"  ROI: {roi:+.2f}%")
        if roi > 4:
            print(f"  ✅ Цель ROI > 4% достигнута!")
        else:
            print(f"  ⏳ Цель ROI > 4% (нужно ещё {4 - roi:.1f}%)")
    else:
        print("  Нет закрытых ставок за 30 дней")

    # По видам спорта
    by_sport = conn.execute("""
        SELECT m.sport,
               COUNT(*) as total,
               SUM(CASE WHEN b.result='won' THEN 1 ELSE 0 END) as wins,
               SUM(COALESCE(b.profit, 0)) as profit
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result IN ('won', 'lost')
          AND COALESCE(b.excluded_from_stats, 0) = 0
          AND b.created_at >= ?
        GROUP BY m.sport
    """, (month_ago,)).fetchall()

    if by_sport:
        print(f"\n  По видам спорта:")
        for s in by_sport:
            roi_s = s["profit"] / max(1, s["total"]) / 1000 * 100
            print(f"  {s['sport']:10s} | {s['total']} ставок | "
                  f"W:{s['wins']} | прибыль: {s['profit']:+.0f} руб")

    # Предстоящие матчи
    upcoming = conn.execute("""
        SELECT sport, league, home_team, away_team, match_date,
               odds_home, odds_draw, odds_away
        FROM matches
        WHERE status='upcoming'
          AND odds_home IS NOT NULL
          AND datetime(match_date) > datetime('now')
          AND datetime(match_date) < datetime('now', '+24 hours')
        ORDER BY match_date
        LIMIT 10
    """).fetchall()

    print(f"\n⏰ МАТЧИ БЛИЖАЙШИЕ 24 ЧАСА: {len(upcoming)}")
    for m in upcoming:
        sport_emoji = "🏒" if m["sport"] == "hockey" else "⚽"
        print(f"  {sport_emoji} {m['match_date'][11:16]} | {m['home_team']} — {m['away_team']}")

    conn.close()
    print(f"\n{'='*60}\n")

if __name__ == "__main__":
    main()
