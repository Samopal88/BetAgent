#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
strategy_portfolio_v3_pruned_walkforward.py

Pruned V3 portfolio + overfitting check.

Keeps only rule families that survived V3:
- DRAW_SA
- DRAW_BL1_FL1
- AWAY_SA
- DRAW_BALANCED_LOW_SCORING_SA
- DRAW_BALANCED_LINE_SA
- DRAW_BALANCED_LINE_BL1
- AWAY_SA_STRICT_PLUS

Removes:
- DRAW_LOW_SCORING_FL1
- DRAW_BALANCED_LINE_FL1
- P1_PD_RELAXED

What it calculates:
- overall portfolio summary
- rule summary
- ROI by year
- ROI by month
- walk-forward annual test report
- flat_1u / flat_pct / kelly_0_10 / kelly_0_25

Usage:
  cd /root/betagent
  source .venv/bin/activate
  python3 strategy_portfolio_v3_pruned_walkforward.py --db /root/betagent/betagent.db
"""

from __future__ import annotations

import argparse
import csv
import json
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
    year: str
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


def parse_dt(s: str) -> datetime:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return datetime.min


def parse_year(s: str) -> str:
    dt = parse_dt(s)
    return dt.strftime("%Y") if dt != datetime.min else "UNKNOWN"


def parse_month(s: str) -> str:
    dt = parse_dt(s)
    return dt.strftime("%Y-%m") if dt != datetime.min else "UNKNOWN"


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
        h.form_last_5_home,
        h.form_last_5_away,
        h.form_points_last_5_home,
        h.form_points_last_5_away,
        h.home_goals_scored_avg,
        h.away_goals_scored_avg,
        h.home_goals_allowed_avg,
        h.away_goals_allowed_avg
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


def league_has(s: str, *parts: str) -> bool:
    s = s.lower()
    return any(p in s for p in parts)


# -------- retained families --------
def rule_draw_sa(r):
    f = feat(r)
    if not league_has(f["league"], "серия а", "serie a"):
        return None
    if not (3.0 <= f["odds_draw"] <= 3.85):
        return None
    if f["pos_gap"] is None or abs(f["pos_gap"]) > 5:
        return None
    if abs(f["form_gap"]) > 3:
        return None
    vals = [f["home_scored"], f["away_scored"], f["home_allowed"], f["away_allowed"]]
    if any(v is None for v in vals):
        return None
    if max(float(f["home_scored"]), float(f["away_scored"])) <= 1.55 and max(float(f["home_allowed"]), float(f["away_allowed"])) <= 1.75:
        return "draw"
    return None


def rule_draw_bl1_fl1(r):
    f = feat(r)
    if not league_has(f["league"], "бундеслига", "bundesliga", "лига 1", "ligue 1"):
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


def rule_away_sa(r):
    f = feat(r)
    if not league_has(f["league"], "серия а", "serie a"):
        return None
    if not (2.05 <= f["odds_away"] <= 3.60):
        return None
    if f["pos_gap"] is None or f["pos_gap"] > -3:
        return None
    if (f["away_form_pts"] - f["home_form_pts"]) < 3:
        return None
    if f["home_allowed"] is None or f["away_scored"] is None:
        return None
    if float(f["home_allowed"]) >= 1.25 and float(f["away_scored"]) >= 1.20:
        return "away"
    return None


def rule_draw_balanced_low_scoring_sa(r):
    f = feat(r)
    if not league_has(f["league"], "серия а", "serie a"):
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


def rule_draw_balanced_line_sa(r):
    f = feat(r)
    if not league_has(f["league"], "серия а", "serie a"):
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


def rule_draw_balanced_line_bl1(r):
    f = feat(r)
    if not league_has(f["league"], "бундеслига", "bundesliga"):
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


def rule_away_sa_strict_plus(r):
    f = feat(r)
    if not league_has(f["league"], "серия а", "serie a"):
        return None
    if not (2.05 <= f["odds_away"] <= 2.85):
        return None
    if f["pos_gap"] is None or f["pos_gap"] > -4:
        return None
    if (f["away_form_pts"] - f["home_form_pts"]) < 4:
        return None
    if f["home_allowed"] is None or f["away_scored"] is None:
        return None
    if float(f["home_allowed"]) >= 1.30 and float(f["away_scored"]) >= 1.25:
        return "away"
    return None


RULES = {
    "DRAW_SA": rule_draw_sa,
    "DRAW_BL1_FL1": rule_draw_bl1_fl1,
    "AWAY_SA": rule_away_sa,
    "DRAW_BALANCED_LOW_SCORING_SA": rule_draw_balanced_low_scoring_sa,
    "DRAW_BALANCED_LINE_SA": rule_draw_balanced_line_sa,
    "DRAW_BALANCED_LINE_BL1": rule_draw_balanced_line_bl1,
    "AWAY_SA_STRICT_PLUS": rule_away_sa_strict_plus,
}


def select_bets(rows: List[sqlite3.Row]) -> List[Bet]:
    bets: List[Bet] = []
    seen = set()
    for r in rows:
        for family, fn in RULES.items():
            market = fn(r)
            if not market:
                continue
            key = (int(r["id"]), family)
            if key in seen:
                continue
            seen.add(key)
            actual = outcome_from_scores(r["home_score"], r["away_score"])
            bets.append(Bet(
                family=family,
                match_id=int(r["id"]),
                match_date=r["match_date"],
                year=parse_year(r["match_date"]),
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


def stake_fractional_kelly(bankroll: float, fraction: float, odds: float, est_p: float) -> float:
    b = odds - 1.0
    q = 1.0 - est_p
    if b <= 0:
        return 0.0
    k = max(0.0, (b * est_p - q) / b)
    return bankroll * k * fraction


def estimate_p_from_family(family: str) -> float:
    priors = {
        "DRAW_SA": 0.40,
        "DRAW_BL1_FL1": 0.39,
        "AWAY_SA": 0.43,
        "DRAW_BALANCED_LOW_SCORING_SA": 0.40,
        "DRAW_BALANCED_LINE_SA": 0.37,
        "DRAW_BALANCED_LINE_BL1": 0.34,
        "AWAY_SA_STRICT_PLUS": 0.42,
    }
    return priors.get(family, 0.35)


def run_staking(bets: List[Bet], mode: str, initial_bankroll: float, flat_pct: float) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    bankroll = initial_bankroll
    peak = bankroll
    max_dd = 0.0
    longest_losing_streak = 0
    cur_ls = 0

    monthly: Dict[str, Dict[str, Any]] = {}
    yearly: Dict[str, Dict[str, Any]] = {}

    total_staked = 0.0
    total_profit = 0.0
    bet_count = 0

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

        stake = round(max(0.0, stake), 2)
        if stake == 0:
            continue

        profit = round(stake * (b.odds - 1.0), 2) if b.won else -stake
        bankroll += profit
        peak = max(peak, bankroll)
        max_dd = max(max_dd, peak - bankroll)

        if b.won:
            cur_ls = 0
        else:
            cur_ls += 1
            longest_losing_streak = max(longest_losing_streak, cur_ls)

        total_staked += stake
        total_profit += profit
        bet_count += 1

        m = monthly.setdefault(b.month, {"bets": 0, "wins": 0, "losses": 0, "staked": 0.0, "profit": 0.0})
        m["bets"] += 1
        m["wins"] += 1 if b.won else 0
        m["losses"] += 0 if b.won else 1
        m["staked"] += stake
        m["profit"] += profit

        y = yearly.setdefault(b.year, {"bets": 0, "wins": 0, "losses": 0, "staked": 0.0, "profit": 0.0})
        y["bets"] += 1
        y["wins"] += 1 if b.won else 0
        y["losses"] += 0 if b.won else 1
        y["staked"] += stake
        y["profit"] += profit

    for bucket in (monthly, yearly):
        for v in bucket.values():
            v["staked"] = round(v["staked"], 2)
            v["profit"] = round(v["profit"], 2)
            v["roi_pct"] = round((v["profit"] / v["staked"] * 100.0), 2) if v["staked"] else 0.0

    summary = {
        "mode": mode,
        "initial_bankroll": initial_bankroll,
        "ending_bankroll": round(bankroll, 2),
        "bets": bet_count,
        "total_staked": round(total_staked, 2),
        "total_profit": round(total_profit, 2),
        "roi_pct": round((total_profit / total_staked * 100.0), 2) if total_staked else 0.0,
        "max_drawdown_abs": round(max_dd, 2),
        "max_drawdown_pct": round((max_dd / peak * 100.0), 2) if peak else 0.0,
        "longest_losing_streak": longest_losing_streak,
        "avg_bets_per_month": round(bet_count / max(1, len(monthly)), 2),
    }
    return summary, monthly, yearly


def summarize_rules(bets: List[Bet]) -> List[Dict[str, Any]]:
    by = {}
    for b in bets:
        d = by.setdefault(b.family, {"family": b.family, "bets": 0, "wins": 0, "losses": 0, "odds_sum": 0.0, "profit_units": 0.0})
        d["bets"] += 1
        d["wins"] += 1 if b.won else 0
        d["losses"] += 0 if b.won else 1
        d["odds_sum"] += b.odds
        d["profit_units"] += (b.odds - 1.0) if b.won else -1.0
    rows = []
    for d in by.values():
        rows.append({
            "family": d["family"],
            "bets": d["bets"],
            "wins": d["wins"],
            "losses": d["losses"],
            "winrate_pct": round(d["wins"] / d["bets"] * 100.0, 2) if d["bets"] else 0.0,
            "avg_odds": round(d["odds_sum"] / d["bets"], 3) if d["bets"] else 0.0,
            "profit_units": round(d["profit_units"], 2),
            "roi_pct": round(d["profit_units"] / d["bets"] * 100.0, 2) if d["bets"] else 0.0,
        })
    return sorted(rows, key=lambda x: (x["roi_pct"], x["profit_units"]), reverse=True)


def walkforward_annual(bets: List[Bet]) -> List[Dict[str, Any]]:
    years = sorted({b.year for b in bets if b.year != "UNKNOWN"})
    results = []
    for i in range(1, len(years)):
        train_years = years[:i]
        test_year = years[i]
        train = [b for b in bets if b.year in train_years]
        test = [b for b in bets if b.year == test_year]
        if not test:
            continue
        train_profit = sum((b.odds - 1.0) if b.won else -1.0 for b in train)
        test_profit = sum((b.odds - 1.0) if b.won else -1.0 for b in test)
        results.append({
            "train_years": ",".join(train_years),
            "test_year": test_year,
            "train_bets": len(train),
            "train_roi_pct": round((train_profit / len(train) * 100.0), 2) if train else 0.0,
            "test_bets": len(test),
            "test_wins": sum(1 for b in test if b.won),
            "test_losses": sum(1 for b in test if not b.won),
            "test_roi_pct": round((test_profit / len(test) * 100.0), 2) if test else 0.0,
        })
    return results


def save_reports(outdir: Path, bets: List[Bet], modes: List[Dict[str, Any]], monthly_by_mode: Dict[str, Dict[str, Dict[str, Any]]], yearly_by_mode: Dict[str, Dict[str, Dict[str, Any]]], rule_summary: List[Dict[str, Any]], walkforward: List[Dict[str, Any]]) -> None:
    outdir.mkdir(parents=True, exist_ok=True)

    (outdir / "portfolio_v3_pruned_bets.json").write_text(json.dumps([asdict(b) for b in bets], ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "portfolio_v3_pruned_modes.json").write_text(json.dumps(modes, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "portfolio_v3_pruned_monthly.json").write_text(json.dumps(monthly_by_mode, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "portfolio_v3_pruned_yearly.json").write_text(json.dumps(yearly_by_mode, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "portfolio_v3_pruned_rule_summary.json").write_text(json.dumps(rule_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "portfolio_v3_pruned_walkforward.json").write_text(json.dumps(walkforward, ensure_ascii=False, indent=2), encoding="utf-8")

    with (outdir / "portfolio_v3_pruned_modes.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(modes[0].keys()))
        w.writeheader()
        w.writerows(modes)

    monthly_rows = []
    for mode, months in monthly_by_mode.items():
        for month, vals in months.items():
            monthly_rows.append({"mode": mode, "month": month, **vals})
    with (outdir / "portfolio_v3_pruned_monthly.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(monthly_rows[0].keys()))
        w.writeheader()
        w.writerows(monthly_rows)

    yearly_rows = []
    for mode, years in yearly_by_mode.items():
        for year, vals in years.items():
            yearly_rows.append({"mode": mode, "year": year, **vals})
    with (outdir / "portfolio_v3_pruned_yearly.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(yearly_rows[0].keys()))
        w.writeheader()
        w.writerows(yearly_rows)

    with (outdir / "portfolio_v3_pruned_rule_summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rule_summary[0].keys()))
        w.writeheader()
        w.writerows(rule_summary)

    with (outdir / "portfolio_v3_pruned_walkforward.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(walkforward[0].keys()))
        w.writeheader()
        w.writerows(walkforward)

    lines = ["PORTFOLIO V3 PRUNED + WALKFORWARD", "=" * 100, "Families included:"]
    for name in RULES:
        lines.append(f"- {name}")
    lines.append("")
    lines.append("RULE SUMMARY:")
    for r in rule_summary:
        lines.append(f"  {r['family']}: bets={r['bets']} roi={r['roi_pct']}% winrate={r['winrate_pct']}% avg_odds={r['avg_odds']}")
    lines.append("-" * 100)
    lines.append("WALKFORWARD ANNUAL TESTS (flat 1u logic):")
    for wf in walkforward:
        lines.append(
            f"  train={wf['train_years']} -> test={wf['test_year']} | "
            f"train_bets={wf['train_bets']} train_roi={wf['train_roi_pct']}% | "
            f"test_bets={wf['test_bets']} test_w/l={wf['test_wins']}/{wf['test_losses']} test_roi={wf['test_roi_pct']}%"
        )
    lines.append("-" * 100)

    for m in sorted(modes, key=lambda x: x["roi_pct"], reverse=True):
        lines.append(f"Mode: {m['mode']}")
        for k in ["initial_bankroll", "ending_bankroll", "bets", "total_staked", "total_profit", "roi_pct",
                  "max_drawdown_abs", "max_drawdown_pct", "longest_losing_streak", "avg_bets_per_month"]:
            lines.append(f"  {k}: {m[k]}")
        lines.append("  Yearly ROI:")
        for year, vals in sorted(yearly_by_mode[m["mode"]].items()):
            lines.append(f"    {year}: bets={vals['bets']} profit={vals['profit']} roi={vals['roi_pct']}%")
        lines.append("-" * 100)

    (outdir / "portfolio_v3_pruned_summary.txt").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--bankroll", type=float, default=100000.0)
    ap.add_argument("--flat-pct", type=float, default=0.01)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = load_rows(conn)
    conn.close()

    bets = select_bets(rows)
    rule_summary = summarize_rules(bets)
    walkforward = walkforward_annual(bets)

    modes = []
    monthly_by_mode = {}
    yearly_by_mode = {}
    for mode in ["flat_1u", "flat_pct", "kelly_0_10", "kelly_0_25"]:
        summary, monthly, yearly = run_staking(bets, mode, args.bankroll, args.flat_pct)
        modes.append(summary)
        monthly_by_mode[mode] = monthly
        yearly_by_mode[mode] = yearly

    save_reports(Path(args.outdir), bets, modes, monthly_by_mode, yearly_by_mode, rule_summary, walkforward)
    print(f"Saved:\n  {Path(args.outdir) / 'portfolio_v3_pruned_summary.txt'}\n  {Path(args.outdir) / 'portfolio_v3_pruned_yearly.csv'}\n  {Path(args.outdir) / 'portfolio_v3_pruned_walkforward.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
