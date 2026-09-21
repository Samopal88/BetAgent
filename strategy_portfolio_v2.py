#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
strategy_portfolio_v2.py

Portfolio backtest for selected football rule families with:
- monthly ROI
- flat vs bankroll % vs fractional Kelly staking
- drawdown
- losing streak
- equity curve summary

Rules included in V2:
CORE:
- DRAW_SA                -> X
- DRAW_BL1_FL1          -> X
- AWAY_SA               -> P2

EXPANSION:
- DRAW_BALANCED_LOW_SCORING (Serie A only) -> X
- DRAW_BALANCED_LINE (Serie A only)        -> X
- DRAW_BALANCED_LINE (Bundesliga only)     -> X

Excluded:
- AWAY_BL1
- AWAY_VALUE_FORM
- HOME_VALUE_FORM
- EPL draw families

Usage:
  cd /root/betagent
  source .venv/bin/activate
  python3 strategy_portfolio_v2.py --db /root/betagent/betagent.db

Optional:
  python3 strategy_portfolio_v2.py --db /root/betagent/betagent.db --bankroll 100000 --flat-pct 0.01
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Bet:
    family: str
    match_id: int
    match_date: str
    month: str
    league: str
    home_team: str
    away_team: str
    market: str
    market_label: str
    odds: float
    actual_outcome: str
    won: bool


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


def label_for_market(m: str) -> str:
    return {"home": "П1", "away": "П2", "draw": "X"}[m]


def parse_month(s: str) -> str:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m")
        except ValueError:
            pass
    return "UNKNOWN"


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
      AND bm.odds_draw IS NOT NULL
      AND bm.odds_away IS NOT NULL
    ORDER BY bm.match_date, bm.id
    """
    return conn.execute(q).fetchall()


def feat(r: sqlite3.Row) -> Dict[str, Any]:
    hp = r["home_position"]
    ap = r["away_position"]
    hfp = r["form_points_last_5_home"] if r["form_points_last_5_home"] is not None else parse_form_points(r["form_last_5_home"])
    afp = r["form_points_last_5_away"] if r["form_points_last_5_away"] is not None else parse_form_points(r["form_last_5_away"])
    return {
        "league": r["league"] or "",
        "home_pos": hp,
        "away_pos": ap,
        "pos_gap": None if hp is None or ap is None else int(ap) - int(hp),  # + home better, - away better
        "home_form_pts": hfp,
        "away_form_pts": afp,
        "form_gap": hfp - afp,  # + home better
        "home_scored": r["home_goals_scored_avg"],
        "away_scored": r["away_goals_scored_avg"],
        "home_allowed": r["home_goals_allowed_avg"],
        "away_allowed": r["away_goals_allowed_avg"],
        "odds_home": float(r["odds_home"]),
        "odds_draw": float(r["odds_draw"]),
        "odds_away": float(r["odds_away"]),
        "actual": outcome_from_scores(r["home_score"], r["away_score"]),
    }


# ---------- Existing BA core approximations ----------
def rule_draw_sa(r: sqlite3.Row) -> Optional[str]:
    f = feat(r)
    league = f["league"].lower()
    if "серия а" not in league and "serie a" not in league:
        return None
    if not (3.0 <= f["odds_draw"] <= 3.85):
        return None
    if f["pos_gap"] is None or abs(f["pos_gap"]) > 5:
        return None
    if abs(f["form_gap"]) > 3:
        return None
    hs, as_ = f["home_scored"], f["away_scored"]
    ha, aa = f["home_allowed"], f["away_allowed"]
    vals = [hs, as_, ha, aa]
    if any(v is None for v in vals):
        return None
    if max(float(hs), float(as_)) <= 1.55 and max(float(ha), float(aa)) <= 1.75:
        return "draw"
    return None


def rule_draw_bl1_fl1(r: sqlite3.Row) -> Optional[str]:
    f = feat(r)
    league = f["league"].lower()
    if not any(x in league for x in ["бундеслига", "bundesliga", "лига 1", "ligue 1"]):
        return None
    if not (3.05 <= f["odds_draw"] <= 3.70):
        return None
    if abs(f["odds_home"] - f["odds_away"]) > 1.05:
        return None
    if min(f["odds_home"], f["odds_away"]) < 1.95:
        return None
    if f["pos_gap"] is None or abs(f["pos_gap"]) > 4:
        return None
    if abs(f["form_gap"]) > 3:
        return None
    return "draw"


def rule_away_sa(r: sqlite3.Row) -> Optional[str]:
    f = feat(r)
    league = f["league"].lower()
    if "серия а" not in league and "serie a" not in league:
        return None
    if not (2.05 <= f["odds_away"] <= 3.60):
        return None
    if f["pos_gap"] is None or f["pos_gap"] > -3:
        return None  # away better by 3+ positions
    if (f["away_form_pts"] - f["home_form_pts"]) < 3:
        return None
    if f["home_allowed"] is None or f["away_scored"] is None:
        return None
    if float(f["home_allowed"]) >= 1.25 and float(f["away_scored"]) >= 1.20:
        return "away"
    return None


# ---------- New expansion families ----------
def rule_draw_balanced_low_scoring_sa(r: sqlite3.Row) -> Optional[str]:
    f = feat(r)
    league = f["league"].lower()
    if "серия а" not in league and "serie a" not in league:
        return None
    if not (3.0 <= f["odds_draw"] <= 3.6):
        return None
    if f["pos_gap"] is None or abs(f["pos_gap"]) > 6:
        return None
    if abs(f["form_gap"]) > 3:
        return None
    vals = [f["home_scored"], f["away_scored"], f["home_allowed"], f["away_allowed"]]
    if any(v is None for v in vals):
        return None
    if max(float(f["home_scored"]), float(f["away_scored"])) > 1.55:
        return None
    if max(float(f["home_allowed"]), float(f["away_allowed"])) > 1.65:
        return None
    return "draw"


def rule_draw_balanced_line_sa(r: sqlite3.Row) -> Optional[str]:
    f = feat(r)
    league = f["league"].lower()
    if "серия а" not in league and "serie a" not in league:
        return None
    if not (3.05 <= f["odds_draw"] <= 3.65):
        return None
    if abs(f["odds_home"] - f["odds_away"]) > 0.95:
        return None
    if min(f["odds_home"], f["odds_away"]) < 2.0:
        return None
    if f["pos_gap"] is None or abs(f["pos_gap"]) > 5:
        return None
    if abs(f["form_gap"]) > 4:
        return None
    return "draw"


def rule_draw_balanced_line_bl1(r: sqlite3.Row) -> Optional[str]:
    f = feat(r)
    league = f["league"].lower()
    if "бундеслига" not in league and "bundesliga" not in league:
        return None
    if not (3.05 <= f["odds_draw"] <= 3.65):
        return None
    if abs(f["odds_home"] - f["odds_away"]) > 0.95:
        return None
    if min(f["odds_home"], f["odds_away"]) < 2.0:
        return None
    if f["pos_gap"] is None or abs(f["pos_gap"]) > 5:
        return None
    if abs(f["form_gap"]) > 4:
        return None
    return "draw"


RULES = {
    "DRAW_SA": rule_draw_sa,
    "DRAW_BL1_FL1": rule_draw_bl1_fl1,
    "AWAY_SA": rule_away_sa,
    "DRAW_BALANCED_LOW_SCORING_SA": rule_draw_balanced_low_scoring_sa,
    "DRAW_BALANCED_LINE_SA": rule_draw_balanced_line_sa,
    "DRAW_BALANCED_LINE_BL1": rule_draw_balanced_line_bl1,
}


def select_bets(rows: List[sqlite3.Row]) -> List[Bet]:
    bets: List[Bet] = []
    seen_keys = set()

    for r in rows:
        for family, fn in RULES.items():
            market = fn(r)
            if not market:
                continue
            key = (int(r["id"]), family)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            actual = outcome_from_scores(r["home_score"], r["away_score"])
            bets.append(Bet(
                family=family,
                match_id=int(r["id"]),
                match_date=r["match_date"],
                month=parse_month(r["match_date"]),
                league=r["league"],
                home_team=r["home_team"],
                away_team=r["away_team"],
                market=market,
                market_label=label_for_market(market),
                odds=float(r[f"odds_{'draw' if market == 'draw' else market}"]),
                actual_outcome=actual,
                won=(market == actual) if actual is not None else False,
            ))
    bets.sort(key=lambda b: (b.match_date, b.match_id, b.family))
    return bets


def stake_flat_unit(bankroll: float, flat_pct: float, _: float, __: float) -> float:
    return bankroll * flat_pct


def stake_fractional_kelly(bankroll: float, fraction: float, odds: float, est_p: float) -> float:
    b = odds - 1.0
    p = est_p
    q = 1.0 - p
    if b <= 0:
        return 0.0
    k = max(0.0, (b * p - q) / b)
    return bankroll * k * fraction


def estimate_p_from_family(family: str) -> float:
    # conservative prior estimates from research
    priors = {
        "DRAW_SA": 0.40,
        "DRAW_BL1_FL1": 0.41,
        "AWAY_SA": 0.43,
        "DRAW_BALANCED_LOW_SCORING_SA": 0.40,
        "DRAW_BALANCED_LINE_SA": 0.37,
        "DRAW_BALANCED_LINE_BL1": 0.34,
    }
    return priors.get(family, 0.35)


def run_staking(bets: List[Bet], mode: str, initial_bankroll: float, flat_pct: float, kelly_fraction: float) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    bankroll = initial_bankroll
    peak = bankroll
    max_dd = 0.0
    longest_losing_streak = 0
    current_losing_streak = 0

    equity_rows: List[Dict[str, Any]] = []
    monthly: Dict[str, Dict[str, Any]] = {}

    for b in bets:
        if mode == "flat_1u":
            stake = 1.0
        elif mode == "flat_pct":
            stake = bankroll * flat_pct
        elif mode == "kelly_0_10":
            stake = stake_fractional_kelly(bankroll, 0.10, b.odds, estimate_p_from_family(b.family))
        elif mode == "kelly_0_25":
            stake = stake_fractional_kelly(bankroll, 0.25, b.odds, estimate_p_from_family(b.family))
        else:
            raise ValueError(mode)

        stake = max(0.0, round(stake, 2))
        if stake == 0:
            continue

        if b.won:
            profit = stake * (b.odds - 1.0)
            bankroll += profit
            current_losing_streak = 0
        else:
            profit = -stake
            bankroll += profit
            current_losing_streak += 1
            longest_losing_streak = max(longest_losing_streak, current_losing_streak)

        peak = max(peak, bankroll)
        dd = (peak - bankroll)
        max_dd = max(max_dd, dd)

        m = monthly.setdefault(b.month, {"bets": 0, "wins": 0, "losses": 0, "staked": 0.0, "profit": 0.0})
        m["bets"] += 1
        m["wins"] += 1 if b.won else 0
        m["losses"] += 0 if b.won else 1
        m["staked"] += stake
        m["profit"] += profit

        equity_rows.append({
            "month": b.month,
            "date": b.match_date,
            "family": b.family,
            "league": b.league,
            "match_id": b.match_id,
            "market": b.market_label,
            "odds": b.odds,
            "won": b.won,
            "stake": round(stake, 2),
            "profit": round(profit, 2),
            "bankroll_after": round(bankroll, 2),
        })

    total_staked = round(sum(r["stake"] for r in equity_rows), 2)
    total_profit = round(sum(r["profit"] for r in equity_rows), 2)
    roi = round((total_profit / total_staked * 100.0), 2) if total_staked else 0.0

    summary = {
        "mode": mode,
        "initial_bankroll": initial_bankroll,
        "ending_bankroll": round(bankroll, 2),
        "bets": len(equity_rows),
        "total_staked": total_staked,
        "total_profit": total_profit,
        "roi_pct": roi,
        "max_drawdown_abs": round(max_dd, 2),
        "max_drawdown_pct": round((max_dd / peak * 100.0), 2) if peak else 0.0,
        "longest_losing_streak": longest_losing_streak,
        "avg_bets_per_month": round(len(equity_rows) / max(1, len(monthly)), 2),
    }

    for month in monthly:
        st = monthly[month]["staked"]
        pr = monthly[month]["profit"]
        monthly[month]["roi_pct"] = round((pr / st * 100.0), 2) if st else 0.0
        monthly[month]["staked"] = round(st, 2)
        monthly[month]["profit"] = round(pr, 2)

    return summary, equity_rows, monthly


def save_reports(outdir: Path, bets: List[Bet], mode_results: List[Dict[str, Any]], monthly_by_mode: Dict[str, Dict[str, Dict[str, Any]]], equity_by_mode: Dict[str, List[Dict[str, Any]]]) -> None:
    outdir.mkdir(parents=True, exist_ok=True)

    (outdir / "portfolio_v2_bets.json").write_text(
        json.dumps([asdict(b) for b in bets], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (outdir / "portfolio_v2_modes.json").write_text(
        json.dumps(mode_results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (outdir / "portfolio_v2_monthly.json").write_text(
        json.dumps(monthly_by_mode, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with (outdir / "portfolio_v2_modes.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(mode_results[0].keys()))
        writer.writeheader()
        writer.writerows(mode_results)

    monthly_rows = []
    for mode, months in monthly_by_mode.items():
        for month, vals in months.items():
            row = {"mode": mode, "month": month, **vals}
            monthly_rows.append(row)
    if monthly_rows:
        with (outdir / "portfolio_v2_monthly.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(monthly_rows[0].keys()))
            writer.writeheader()
            writer.writerows(monthly_rows)

    lines = []
    lines.append("PORTFOLIO V2 SUMMARY")
    lines.append("=" * 100)
    lines.append("Families included:")
    for name in RULES:
        lines.append(f"- {name}")
    lines.append("")

    for r in sorted(mode_results, key=lambda x: x["roi_pct"], reverse=True):
        lines.append(f"Mode: {r['mode']}")
        lines.append(f"  initial_bankroll     : {r['initial_bankroll']}")
        lines.append(f"  ending_bankroll      : {r['ending_bankroll']}")
        lines.append(f"  bets                 : {r['bets']}")
        lines.append(f"  total_staked         : {r['total_staked']}")
        lines.append(f"  total_profit         : {r['total_profit']}")
        lines.append(f"  roi_pct              : {r['roi_pct']}%")
        lines.append(f"  max_drawdown_abs     : {r['max_drawdown_abs']}")
        lines.append(f"  max_drawdown_pct     : {r['max_drawdown_pct']}%")
        lines.append(f"  longest_losing_streak: {r['longest_losing_streak']}")
        lines.append(f"  avg_bets_per_month   : {r['avg_bets_per_month']}")
        lines.append("  Monthly ROI:")
        for month, vals in sorted(monthly_by_mode[r["mode"]].items()):
            lines.append(
                f"    {month}: bets={vals['bets']} wins={vals['wins']} losses={vals['losses']} "
                f"profit={vals['profit']} roi={vals['roi_pct']}%"
            )
        lines.append("-" * 100)

    (outdir / "portfolio_v2_summary.txt").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--bankroll", type=float, default=100000.0)
    ap.add_argument("--flat-pct", type=float, default=0.01)
    args = ap.parse_args()

    outdir = Path(args.outdir)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = load_rows(conn)
    conn.close()

    bets = select_bets(rows)

    modes = ["flat_1u", "flat_pct", "kelly_0_10", "kelly_0_25"]
    mode_results = []
    monthly_by_mode: Dict[str, Dict[str, Dict[str, Any]]] = {}
    equity_by_mode: Dict[str, List[Dict[str, Any]]] = {}

    for mode in modes:
        summary, equity_rows, monthly = run_staking(
            bets=bets,
            mode=mode,
            initial_bankroll=args.bankroll,
            flat_pct=args.flat_pct,
            kelly_fraction=0.10,
        )
        mode_results.append(summary)
        monthly_by_mode[mode] = monthly
        equity_by_mode[mode] = equity_rows

    save_reports(outdir, bets, mode_results, monthly_by_mode, equity_by_mode)
    print(f"Saved:\n  {outdir / 'portfolio_v2_summary.txt'}\n  {outdir / 'portfolio_v2_modes.csv'}\n  {outdir / 'portfolio_v2_monthly.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
