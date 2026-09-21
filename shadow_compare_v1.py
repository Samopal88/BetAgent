#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BETAGENT — SHADOW COMPARE V1

Сравнивает два агента по уже сохранённым shadow_recommendations
и по завершённым матчам из таблицы matches.

Важно:
- считает только ПОСЛЕДНЮЮ рекомендацию каждого агента на матч
- если матч ещё не завершён, он не попадёт в расчёт

Запуск:
  python shadow_compare_v1.py
  python shadow_compare_v1.py --sport football
  python shadow_compare_v1.py --agent-a old_agent_v7 --agent-b new_smart_v1
"""

from __future__ import annotations
import os
import sqlite3
import json
import argparse
from pathlib import Path

DB_PATH = Path(os.getenv("BETAGENT_DB_PATH", os.getenv("BETAGENT_DB", "betagent.db")))


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def market_won(market, home_score, away_score):
    if market == "home":
        return home_score > away_score
    if market == "draw":
        return home_score == away_score
    if market == "away":
        return away_score > home_score
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default=None)
    ap.add_argument("--agent-a", default="old_agent_v7")
    ap.add_argument("--agent-b", default="new_smart_v1")
    args = ap.parse_args()

    conn = get_conn()

    q = """
    WITH latest AS (
        SELECT sr.*
        FROM shadow_recommendations sr
        JOIN (
            SELECT agent_name, match_id, MAX(id) AS max_id
            FROM shadow_recommendations
            GROUP BY agent_name, match_id
        ) t
        ON sr.id = t.max_id
    )
    SELECT l.*, m.home_score, m.away_score, m.status
    FROM latest l
    JOIN matches m ON m.id = l.match_id
    WHERE l.agent_name IN (?, ?)
      AND l.valid = 1
      AND m.home_score IS NOT NULL
      AND m.away_score IS NOT NULL
    """
    params = [args.agent_a, args.agent_b]
    if args.sport:
        q += " AND l.sport = ?"
        params.append(args.sport)

    rows = conn.execute(q, params).fetchall()
    by_agent = {}

    for agent in (args.agent_a, args.agent_b):
        subset = [r for r in rows if r["agent_name"] == agent]
        bets = len(subset)
        wins = 0
        staked = 0.0
        profit = 0.0
        for r in subset:
            stake_pct = float(r["stake_pct"] or 0.0)
            odds = float(r["odds"] or 0.0)
            bankroll = 100000.0
            stake = bankroll * stake_pct
            staked += stake
            won = market_won(r["market"], int(r["home_score"]), int(r["away_score"]))
            if won:
                wins += 1
                profit += stake * (odds - 1.0)
            else:
                profit -= stake
        roi = (profit / staked * 100.0) if staked else 0.0
        hit = (wins / bets * 100.0) if bets else 0.0
        by_agent[agent] = (bets, wins, hit, staked, profit, roi)

    print("=" * 90)
    print("SHADOW COMPARE")
    print("=" * 90)
    for agent, vals in by_agent.items():
        bets, wins, hit, staked, profit, roi = vals
        print(f"{agent:<15} | bets={bets:>3} | wins={wins:>3} | hit={hit:>6.2f}% | staked={staked:>10.2f} | profit={profit:>10.2f} | ROI={roi:>7.2f}%")
    print("=" * 90)

    conn.close()


if __name__ == "__main__":
    main()
