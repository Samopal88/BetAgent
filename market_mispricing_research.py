#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
market_mispricing_research.py

Research script for finding where the market may be mispricing football matches
using:
- backtest_matches
- historical_match_features

Outputs:
- reports/underdog_stats.txt
- reports/rule_hypotheses.txt
- reports/rule_hypotheses.csv
- reports/rule_hypotheses.json

Usage:
  cd /root/betagent
  source .venv/bin/activate
  python3 market_mispricing_research.py --db /root/betagent/betagent.db
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


REPORTS = Path("reports")


def parse_form_points(raw: Any) -> int:
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        try:
            arr = json.loads(raw)
            mp = {"W": 3, "D": 1, "L": 0}
            return sum(mp.get(str(x).upper(), 0) for x in arr)
        except Exception:
            return 0
    return 0


def outcome_from_scores(h: Optional[int], a: Optional[int]) -> Optional[str]:
    if h is None or a is None:
        return None
    if h > a:
        return "home"
    if h < a:
        return "away"
    return "draw"


def market_profit(market: str, odds: float, actual: str) -> float:
    if actual is None:
        return 0.0
    if market == actual:
        return odds - 1.0
    return -1.0


@dataclass
class RuleResult:
    family: str
    league: str
    market: str
    sample: int
    wins: int
    losses: int
    winrate_pct: float
    avg_odds: float
    profit_units: float
    roi_pct: float


def load_rows(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    q = """
    SELECT
        bm.id,
        COALESCE(bm.league_name, bm.league) AS league,
        bm.match_date,
        bm.home_team,
        bm.away_team,
        bm.odds_home,
        bm.odds_draw,
        bm.odds_away,
        bm.home_score,
        bm.away_score,

        h.home_position,
        h.away_position,
        h.home_points,
        h.away_points,
        h.form_last_5_home,
        h.form_last_5_away,
        h.form_points_last_5_home,
        h.form_points_last_5_away,
        h.home_goals_scored_avg,
        h.away_goals_scored_avg,
        h.home_goals_allowed_avg,
        h.away_goals_allowed_avg,
        h.h2h_matches_count
    FROM backtest_matches bm
    JOIN historical_match_features h
      ON h.match_id = bm.id
    WHERE bm.home_score IS NOT NULL
      AND bm.away_score IS NOT NULL
      AND bm.odds_home IS NOT NULL
      AND bm.odds_away IS NOT NULL
      AND bm.odds_draw IS NOT NULL
    ORDER BY bm.id
    """
    return conn.execute(q).fetchall()


def build_features(r: sqlite3.Row) -> Dict[str, Any]:
    hp = r["home_position"]
    ap = r["away_position"]
    hfp = r["form_points_last_5_home"] if r["form_points_last_5_home"] is not None else parse_form_points(r["form_last_5_home"])
    afp = r["form_points_last_5_away"] if r["form_points_last_5_away"] is not None else parse_form_points(r["form_last_5_away"])

    return {
        "league": r["league"] or "",
        "actual": outcome_from_scores(r["home_score"], r["away_score"]),
        "home_pos": hp,
        "away_pos": ap,
        "pos_gap": None if hp is None or ap is None else int(ap) - int(hp),  # + => home better
        "home_form_pts": hfp,
        "away_form_pts": afp,
        "form_gap": hfp - afp,  # + => home better
        "home_scored": r["home_goals_scored_avg"],
        "away_scored": r["away_goals_scored_avg"],
        "home_allowed": r["home_goals_allowed_avg"],
        "away_allowed": r["away_goals_allowed_avg"],
        "odds_home": float(r["odds_home"]),
        "odds_draw": float(r["odds_draw"]),
        "odds_away": float(r["odds_away"]),
    }


def underdog_stats(rows: List[sqlite3.Row]) -> Dict[str, Any]:
    stats = {
        "matches": 0,
        "home_underdog_count": 0,
        "home_underdog_wins": 0,
        "away_underdog_count": 0,
        "away_underdog_wins": 0,
        "draw_count": 0,
        "favorite_count": 0,
        "favorite_wins": 0,
    }

    for r in rows:
        actual = outcome_from_scores(r["home_score"], r["away_score"])
        oh, oa = float(r["odds_home"]), float(r["odds_away"])
        stats["matches"] += 1
        if actual == "draw":
            stats["draw_count"] += 1

        if oh < oa:
            stats["favorite_count"] += 1
            if actual == "home":
                stats["favorite_wins"] += 1
            stats["away_underdog_count"] += 1
            if actual == "away":
                stats["away_underdog_wins"] += 1
        elif oa < oh:
            stats["favorite_count"] += 1
            if actual == "away":
                stats["favorite_wins"] += 1
            stats["home_underdog_count"] += 1
            if actual == "home":
                stats["home_underdog_wins"] += 1

    return stats


def test_rule_family(rows: List[sqlite3.Row], league_name: str, family: str) -> Optional[RuleResult]:
    picked = []
    for r in rows:
        f = build_features(r)
        league = f["league"].lower()
        if league_name != "ALL" and league_name.lower() not in league:
            continue

        market = None

        if family == "DRAW_BALANCED_LOW_SCORING":
            if 3.0 <= f["odds_draw"] <= 3.6 and f["pos_gap"] is not None and abs(f["pos_gap"]) <= 6:
                if abs(f["form_gap"]) <= 3:
                    vals = [f["home_scored"], f["away_scored"], f["home_allowed"], f["away_allowed"]]
                    if all(v is not None for v in vals):
                        if max(float(f["home_scored"]), float(f["away_scored"])) <= 1.55 and max(float(f["home_allowed"]), float(f["away_allowed"])) <= 1.65:
                            market = "draw"

        elif family == "DRAW_BALANCED_LINE":
            if 3.05 <= f["odds_draw"] <= 3.65 and abs(f["odds_home"] - f["odds_away"]) <= 0.95:
                if min(f["odds_home"], f["odds_away"]) >= 2.0 and f["pos_gap"] is not None and abs(f["pos_gap"]) <= 5:
                    if abs(f["form_gap"]) <= 4:
                        market = "draw"

        elif family == "AWAY_VALUE_FORM":
            if 2.05 <= f["odds_away"] <= 3.10 and f["pos_gap"] is not None:
                # pos_gap positive => home better; negative => away better
                away_better = f["pos_gap"] <= -3
                away_form_better = (f["away_form_pts"] - f["home_form_pts"]) >= 3
                if away_better and away_form_better:
                    if f["home_allowed"] is not None and f["away_scored"] is not None:
                        if float(f["home_allowed"]) >= 1.25 and float(f["away_scored"]) >= 1.20:
                            market = "away"

        elif family == "HOME_VALUE_FORM":
            if 1.85 <= f["odds_home"] <= 2.60 and f["pos_gap"] is not None:
                home_better = f["pos_gap"] >= 3
                home_form_better = (f["home_form_pts"] - f["away_form_pts"]) >= 3
                if home_better and home_form_better:
                    if f["away_allowed"] is not None and f["home_scored"] is not None:
                        if float(f["away_allowed"]) >= 1.25 and float(f["home_scored"]) >= 1.20:
                            market = "home"

        if market:
            odds = f[f"odds_{market}"]
            actual = f["actual"]
            picked.append((market, odds, actual))

    if not picked:
        return None

    wins = sum(1 for m, _, a in picked if m == a)
    losses = sum(1 for m, _, a in picked if m != a)
    profit = sum(market_profit(m, o, a) for m, o, a in picked)
    avg_odds = sum(o for _, o, _ in picked) / len(picked)
    roi = profit / len(picked) * 100.0 if picked else 0.0
    market_name = picked[0][0]
    return RuleResult(
        family=family,
        league=league_name,
        market=market_name,
        sample=len(picked),
        wins=wins,
        losses=losses,
        winrate_pct=round(wins / len(picked) * 100.0, 2),
        avg_odds=round(avg_odds, 3),
        profit_units=round(profit, 2),
        roi_pct=round(roi, 2),
    )


def write_underdog_report(stats: Dict[str, Any], outdir: Path) -> None:
    txt = outdir / "underdog_stats.txt"
    lines = [
        "UNDERDOG / FAVORITE STATS",
        "=" * 80,
        f"matches: {stats['matches']}",
        f"draw_count: {stats['draw_count']} ({stats['draw_count'] / stats['matches'] * 100:.2f}%)",
        f"favorite_wins: {stats['favorite_wins']} / {stats['favorite_count']} ({(stats['favorite_wins'] / stats['favorite_count'] * 100) if stats['favorite_count'] else 0:.2f}%)",
        f"home_underdog_wins: {stats['home_underdog_wins']} / {stats['home_underdog_count']} ({(stats['home_underdog_wins'] / stats['home_underdog_count'] * 100) if stats['home_underdog_count'] else 0:.2f}%)",
        f"away_underdog_wins: {stats['away_underdog_wins']} / {stats['away_underdog_count']} ({(stats['away_underdog_wins'] / stats['away_underdog_count'] * 100) if stats['away_underdog_count'] else 0:.2f}%)",
    ]
    txt.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--outdir", default="reports")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = load_rows(conn)
    conn.close()

    stats = underdog_stats(rows)
    write_underdog_report(stats, outdir)

    leagues = [
        "ALL",
        "Италия. Серия А",
        "Германия. Бундеслига",
        "Франция. Лига 1",
        "Испания. Примера дивизион",
        "Англия. Премьер-Лига",
    ]
    families = [
        "DRAW_BALANCED_LOW_SCORING",
        "DRAW_BALANCED_LINE",
        "AWAY_VALUE_FORM",
        "HOME_VALUE_FORM",
    ]

    results: List[RuleResult] = []
    for league in leagues:
        for fam in families:
            rr = test_rule_family(rows, league, fam)
            if rr is not None:
                results.append(rr)

    json_path = outdir / "rule_hypotheses.json"
    csv_path = outdir / "rule_hypotheses.csv"
    txt_path = outdir / "rule_hypotheses.txt"

    json_path.write_text(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(r) for r in results)

    lines = ["RULE HYPOTHESES", "=" * 80]
    for r in sorted(results, key=lambda x: (x.roi_pct, x.profit_units, x.sample), reverse=True):
        lines.append(
            f"{r.family} | {r.league} | market={r.market} | "
            f"sample={r.sample} wins={r.wins} losses={r.losses} "
            f"winrate={r.winrate_pct}% avg_odds={r.avg_odds} "
            f"profit_units={r.profit_units} roi={r.roi_pct}%"
        )
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Saved:\n  {outdir / 'underdog_stats.txt'}\n  {txt_path}\n  {csv_path}\n  {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
