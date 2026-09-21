#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import os
import sqlite3
import argparse
from pathlib import Path

DB_PATH = Path(os.getenv("BETAGENT_DB_PATH", os.getenv("BETAGENT_DB", "betagent.db")))
DEFAULT_BANKROLL = 100000.0


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def market_won(market: str, home_score: int, away_score: int) -> bool:
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
    ap.add_argument("--agent", default=None, help="old_agent_v7 | new_smart_v1")
    ap.add_argument("--bankroll", type=float, default=DEFAULT_BANKROLL)
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
    SELECT
        l.agent_name,
        l.match_id,
        l.sport,
        l.home_team,
        l.away_team,
        l.market,
        l.market_label,
        l.odds,
        l.stake_pct,
        l.valid,
        l.created_at,
        m.home_score,
        m.away_score,
        m.status
    FROM latest l
    JOIN matches m ON m.id = l.match_id
    WHERE m.home_score IS NOT NULL
      AND m.away_score IS NOT NULL
      AND l.market IS NOT NULL
      AND lower(l.market) <> 'pass'
    """
    params = []

    if args.sport:
        q += " AND l.sport = ?"
        params.append(args.sport)

    if args.agent:
        q += " AND l.agent_name = ?"
        params.append(args.agent)

    q += " ORDER BY l.agent_name, l.created_at DESC"

    rows = conn.execute(q, params).fetchall()

    if not rows:
        print("=" * 100)
        print("SHADOW COMPARE ALL PICKS")
        print("=" * 100)
        print("Нет завершённых shadow-рекомендаций с market != PASS.")
        conn.close()
        return 0

    by_agent = {}

    for r in rows:
        agent = r["agent_name"]
        if agent not in by_agent:
            by_agent[agent] = {
                "bets": 0,
                "wins": 0,
                "losses": 0,
                "staked": 0.0,
                "profit": 0.0,
                "valid_1": 0,
                "valid_0": 0,
                "examples": [],
            }

        market = (r["market"] or "").strip().lower()
        odds = float(r["odds"] or 0.0)
        stake_pct = float(r["stake_pct"] or 0.0)

        # Если stake_pct пустой/нулевой — всё равно считаем "условную ставку"
        # по 1% банка, чтобы сравнить направление сигналов.
        if stake_pct <= 0:
            stake_pct = 0.01

        stake = args.bankroll * stake_pct
        won = market_won(market, int(r["home_score"]), int(r["away_score"]))

        by_agent[agent]["bets"] += 1
        by_agent[agent]["staked"] += stake

        if str(r["valid"]) in ("1", "true", "True", "TRUE"):
            by_agent[agent]["valid_1"] += 1
        else:
            by_agent[agent]["valid_0"] += 1

        if won:
            by_agent[agent]["wins"] += 1
            by_agent[agent]["profit"] += stake * (odds - 1.0)
            result_label = "W"
        else:
            by_agent[agent]["losses"] += 1
            by_agent[agent]["profit"] -= stake
            result_label = "L"

        if len(by_agent[agent]["examples"]) < 12:
            by_agent[agent]["examples"].append(
                f"{r['home_team']} - {r['away_team']} | {market} @ {odds} | "
                f"{r['home_score']}:{r['away_score']} | {result_label} | valid={r['valid']}"
            )

    print("=" * 100)
    print("SHADOW COMPARE ALL PICKS (ignore valid filter)")
    print("=" * 100)

    for agent, s in by_agent.items():
        bets = s["bets"]
        wins = s["wins"]
        losses = s["losses"]
        staked = s["staked"]
        profit = s["profit"]
        roi = (profit / staked * 100.0) if staked else 0.0
        hit = (wins / bets * 100.0) if bets else 0.0

        print(
            f"{agent:<15} | bets={bets:>3} | wins={wins:>3} | losses={losses:>3} | "
            f"hit={hit:>6.2f}% | staked={staked:>10.2f} | profit={profit:>10.2f} | "
            f"ROI={roi:>7.2f}% | valid1={s['valid_1']:>3} | valid0={s['valid_0']:>3}"
        )

    print("=" * 100)
    print("EXAMPLES")
    print("=" * 100)
    for agent, s in by_agent.items():
        print(f"\n[{agent}]")
        for ex in s["examples"]:
            print(" -", ex)

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
