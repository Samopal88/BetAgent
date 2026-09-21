#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experimental_rule_family_runner.py

Standalone tester for NEW experimental football rule families using:
- backtest_matches
- historical_match_features

This does not modify agent_handoff_v7.py.
It lets you test new rule families separately before embedding them.

Usage:
  cd /root/betagent
  source .venv/bin/activate
  python3 experimental_rule_family_runner.py --db /root/betagent/betagent.db
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class RuleBet:
    family: str
    match_id: int
    league: str
    home_team: str
    away_team: str
    market: str
    market_label: str
    odds: float
    actual_outcome: Optional[str]
    won: Optional[bool]


def parse_form_points(raw: Any) -> int:
    if raw is None:
        return 0
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            arr = json.loads(raw)
            mp = {"W": 3, "D": 1, "L": 0}
            return sum(mp.get(str(x).upper(), 0) for x in arr)
        except Exception:
            return 0
    return 0


def label_for_market(m: str) -> str:
    return {"home": "П1", "away": "П2", "draw": "X"}[m]


def outcome_from_scores(h: Optional[int], a: Optional[int]) -> Optional[str]:
    if h is None or a is None:
        return None
    if h > a:
        return "home"
    if h < a:
        return "away"
    return "draw"


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
    ORDER BY bm.id
    """
    return conn.execute(q).fetchall()


def family_draw_balanced_low_scoring(r: sqlite3.Row) -> Optional[str]:
    league = (r["league"] or "").lower()
    if not any(x in league for x in ["серия а", "бундеслига", "лига 1", "serie a", "bundesliga", "ligue 1"]):
        return None
    if r["odds_draw"] is None:
        return None
    if not (3.0 <= float(r["odds_draw"]) <= 3.6):
        return None

    hp, ap = r["home_position"], r["away_position"]
    if hp is None or ap is None or abs(int(hp) - int(ap)) > 6:
        return None

    hfp = parse_form_points(r["form_points_last_5_home"])
    afp = parse_form_points(r["form_points_last_5_away"])
    if abs(hfp - afp) > 3:
        return None

    hgs, ags = r["home_goals_scored_avg"], r["away_goals_scored_avg"]
    hga, aga = r["home_goals_allowed_avg"], r["away_goals_allowed_avg"]
    vals = [hgs, ags, hga, aga]
    if any(v is None for v in vals):
        return None
    if max(float(hgs), float(ags)) > 1.55:
        return None
    if max(float(hga), float(aga)) > 1.65:
        return None

    return "draw"


def family_draw_balanced_line(r: sqlite3.Row) -> Optional[str]:
    league = (r["league"] or "").lower()
    if not any(x in league for x in ["серия а", "бундеслига", "лига 1", "serie a", "bundesliga", "ligue 1"]):
        return None
    if None in (r["odds_home"], r["odds_draw"], r["odds_away"]):
        return None

    oh, od, oa = float(r["odds_home"]), float(r["odds_draw"]), float(r["odds_away"])
    if not (3.05 <= od <= 3.65):
        return None
    if abs(oh - oa) > 0.95:
        return None
    if min(oh, oa) < 2.0:
        return None

    hp, ap = r["home_position"], r["away_position"]
    if hp is None or ap is None or abs(int(hp) - int(ap)) > 5:
        return None

    hfp = parse_form_points(r["form_points_last_5_home"])
    afp = parse_form_points(r["form_points_last_5_away"])
    if abs(hfp - afp) > 4:
        return None

    return "draw"


def family_away_value_form(r: sqlite3.Row) -> Optional[str]:
    league = (r["league"] or "").lower()
    if not any(x in league for x in ["серия а", "бундеслига", "serie a", "bundesliga"]):
        return None
    if r["odds_away"] is None:
        return None
    oa = float(r["odds_away"])
    if not (2.05 <= oa <= 3.10):
        return None

    hp, ap = r["home_position"], r["away_position"]
    if hp is None or ap is None:
        return None
    if int(ap) + 3 > int(hp):
        return None

    hfp = parse_form_points(r["form_points_last_5_home"])
    afp = parse_form_points(r["form_points_last_5_away"])
    if afp < hfp + 3:
        return None

    hga = r["home_goals_allowed_avg"]
    ags = r["away_goals_scored_avg"]
    if hga is None or ags is None:
        return None
    if float(hga) < 1.25 or float(ags) < 1.20:
        return None

    return "away"


FAMILIES = {
    "DRAW_BALANCED_LOW_SCORING": family_draw_balanced_low_scoring,
    "DRAW_BALANCED_LINE": family_draw_balanced_line,
    "AWAY_VALUE_FORM": family_away_value_form,
}


def evaluate_family(name: str, rows: List[sqlite3.Row]) -> tuple[Dict[str, Any], List[RuleBet]]:
    bets: List[RuleBet] = []
    for r in rows:
        market = FAMILIES[name](r)
        if not market:
            continue
        actual = outcome_from_scores(r["home_score"], r["away_score"])
        won = None if actual is None else (market == actual)
        odds = float(r[f"odds_{'draw' if market == 'draw' else market}"])
        bets.append(RuleBet(
            family=name,
            match_id=int(r["id"]),
            league=r["league"],
            home_team=r["home_team"],
            away_team=r["away_team"],
            market=market,
            market_label=label_for_market(market),
            odds=odds,
            actual_outcome=actual,
            won=won,
        ))

    settled = [b for b in bets if b.actual_outcome]
    wins = sum(1 for b in settled if b.won is True)
    losses = sum(1 for b in settled if b.won is False)
    staked = float(len(settled))  # flat stake 1u
    profit = 0.0
    for b in settled:
        if b.won:
            profit += b.odds - 1.0
        else:
            profit -= 1.0
    roi = (profit / staked * 100.0) if staked else 0.0

    summary = {
        "family": name,
        "bets": len(bets),
        "settled": len(settled),
        "wins": wins,
        "losses": losses,
        "winrate_pct": round((wins / len(settled) * 100.0), 2) if settled else 0.0,
        "profit_units": round(profit, 2),
        "roi_pct": round(roi, 2),
        "avg_odds": round(sum(b.odds for b in bets) / len(bets), 3) if bets else 0.0,
        "draw_count": sum(1 for b in bets if b.market == "draw"),
        "away_count": sum(1 for b in bets if b.market == "away"),
        "home_count": sum(1 for b in bets if b.market == "home"),
    }
    return summary, bets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--outdir", default="reports")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = load_rows(conn)
    conn.close()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    summaries = []
    for name in FAMILIES:
        summary, bets = evaluate_family(name, rows)
        summaries.append(summary)
        (outdir / f"{name}.bets.json").write_text(
            json.dumps([asdict(b) for b in bets], ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    json_path = outdir / "experimental_rule_families.json"
    csv_path = outdir / "experimental_rule_families.csv"
    txt_path = outdir / "experimental_rule_families.txt"

    json_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summaries[0].keys()))
        writer.writeheader()
        writer.writerows(summaries)

    lines = ["EXPERIMENTAL RULE FAMILIES", "=" * 80]
    for s in sorted(summaries, key=lambda x: (x["roi_pct"], x["profit_units"]), reverse=True):
        lines.append(
            f'{s["family"]}: bets={s["bets"]} wins={s["wins"]} losses={s["losses"]} '
            f'winrate={s["winrate_pct"]}% avg_odds={s["avg_odds"]} '
            f'profit_units={s["profit_units"]} roi={s["roi_pct"]}%'
        )
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Saved:\n  {json_path}\n  {csv_path}\n  {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
