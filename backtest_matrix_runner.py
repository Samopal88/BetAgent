#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_matrix_runner.py

Standalone research runner for football backtests.
Does NOT require adding new CLI flags to agent_handoff_v7.py.

What it does:
- imports agent_handoff_v7 as a module
- runs many scenario configurations
- uses historical_match_features when available
- supports:
  * league filter
  * market filter (ALL/P1/P2/X)
  * BA-only mode
  * edge threshold override
  * no-lineup cap override
  * max stake pct override
- writes consolidated reports

Usage:
  cd /root/betagent
  source .venv/bin/activate
  set -a && source .env && set +a
  python3 backtest_matrix_runner.py

Optional:
  python3 backtest_matrix_runner.py --limit 2000 --bankroll 100000
  python3 backtest_matrix_runner.py --quick
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
from copy import deepcopy
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path("/root/betagent")
sys.path.insert(0, str(ROOT))

import agent_handoff_v7 as ag  # noqa: E402


REPORTS = ROOT / "reports"


@dataclass
class Scenario:
    name: str
    league: Optional[str] = None
    market_filter: str = "ALL"   # ALL / P1 / P2 / X
    only_ba: bool = False
    pure_ba: bool = False
    edge_threshold: Optional[float] = None
    no_lineup_cap: Optional[float] = None
    max_stake_pct: Optional[float] = None
    limit: int = 2000


@dataclass
class BetRow:
    match_id: int
    league: str
    home_team: str
    away_team: str
    market: str
    market_label: str
    odds: float
    stake_abs: float
    ba_rule: Optional[str]
    shortlist_source: str
    actual_outcome: Optional[str]
    won: Optional[bool]
    using_hist: bool


@dataclass
class ScenarioResult:
    scenario_name: str
    league: Optional[str]
    market_filter: str
    only_ba: bool
    pure_ba: bool
    edge_threshold: Optional[float]
    no_lineup_cap: Optional[float]
    max_stake_pct: Optional[float]
    matches_seen: int
    matches_after_league: int
    preflight_skip: int
    ba_bypass_count: int
    bets: int
    settled: int
    wins: int
    losses: int
    no_result: int
    staked: float
    profit: float
    roi: float
    p1_count: int
    p2_count: int
    x_count: int
    ba_count: int
    ba_draw_sa: int
    ba_away_sa: int
    ba_p1_pd: int
    ba_draw_bl1_fl1: int
    ba_away_bl1: int
    hist_bets: int
    output_file: str
    bets_file: str


STARTER_SCENARIOS: List[Scenario] = [
    Scenario("all_all_baseline", limit=2000),
    Scenario("all_all_conservative", edge_threshold=0.05, no_lineup_cap=0.53, max_stake_pct=0.015, limit=2000),
    Scenario("all_all_only_ba", only_ba=True, limit=2000),
    Scenario("all_all_pure_ba", only_ba=True, pure_ba=True, limit=2000),

    Scenario("seriea_x_baseline", league="Италия. Серия А", market_filter="X", limit=2000),
    Scenario("seriea_p2_only_ba", league="Италия. Серия А", market_filter="P2", only_ba=True, limit=2000),
    Scenario("seriea_draw_pure_ba", league="Италия. Серия А", market_filter="X", only_ba=True, pure_ba=True, limit=2000),

    Scenario("laliga_p1_only_ba", league="Испания. Примера дивизион", market_filter="P1", only_ba=True, limit=2000),
    Scenario("laliga_p1_pure_ba", league="Испания. Примера дивизион", market_filter="P1", only_ba=True, pure_ba=True, limit=2000),

    Scenario("bundesliga_p2_only_ba", league="Германия. Бундеслига", market_filter="P2", only_ba=True, limit=2000),
    Scenario("bundesliga_x_only_ba", league="Германия. Бундеслига", market_filter="X", only_ba=True, limit=2000),
    Scenario("bundesliga_draw_pure_ba", league="Германия. Бундеслига", market_filter="X", only_ba=True, pure_ba=True, limit=2000),
    Scenario("bundesliga_away_pure_ba", league="Германия. Бундеслига", market_filter="P2", only_ba=True, pure_ba=True, limit=2000),

    Scenario("epl_all_baseline", league="Англия. Премьер-Лига", limit=2000),
    Scenario("ligue1_x_baseline", league="Франция. Лига 1", market_filter="X", limit=2000),

    Scenario("all_p1_conservative", market_filter="P1", edge_threshold=0.05, no_lineup_cap=0.53, max_stake_pct=0.015, limit=2000),
    Scenario("all_p2_conservative", market_filter="P2", edge_threshold=0.05, no_lineup_cap=0.53, max_stake_pct=0.015, limit=2000),
]

QUICK_SCENARIOS: List[Scenario] = [
    Scenario("quick_all_baseline", limit=300),
    Scenario("quick_all_only_ba", only_ba=True, limit=300),
    Scenario("quick_all_pure_ba", only_ba=True, pure_ba=True, limit=300),
    Scenario("quick_all_conservative", edge_threshold=0.05, no_lineup_cap=0.53, max_stake_pct=0.015, limit=300),
]


def market_label_for(rec: Dict[str, Any]) -> str:
    label_map = {"home": "П1", "draw": "X", "away": "П2", "pass": "PASS"}
    return rec.get("market_label") or label_map.get(rec.get("market"), str(rec.get("market")))


def load_historical(conn: sqlite3.Connection) -> Dict[int, Dict[str, Any]]:
    try:
        return ag.load_historical_features(conn)
    except Exception:
        return {}


def league_match(match_league: str, wanted: Optional[str]) -> bool:
    if not wanted:
        return True
    return (match_league or "").strip().lower() == wanted.strip().lower()


def set_profile_overrides(sport: str, edge_threshold: Optional[float], no_lineup_cap: Optional[float]) -> Dict[str, Any]:
    original = deepcopy(ag.SPORT_PROFILES.get(sport, {}))
    profile = deepcopy(ag.get_profile(sport))
    if edge_threshold is not None:
        profile["min_edge_vs_market"] = edge_threshold
    if no_lineup_cap is not None:
        profile["no_lineup_cap"] = no_lineup_cap
        # keep weak cap not above no_lineup_cap
        weak = profile.get("weak_no_lineup_cap", no_lineup_cap)
        profile["weak_no_lineup_cap"] = min(weak, no_lineup_cap)
    ag.SPORT_PROFILES[sport] = profile
    return original


def restore_profile(sport: str, original: Dict[str, Any]) -> None:
    if original:
        ag.SPORT_PROFILES[sport] = original
    else:
        ag.SPORT_PROFILES.pop(sport, None)


def apply_market_filter(rec: Dict[str, Any], market_filter: str) -> bool:
    if market_filter == "ALL":
        return True
    label = market_label_for(rec)
    return label == market_filter


def run_scenario(s: Scenario, bankroll: float) -> tuple[ScenarioResult, List[BetRow]]:
    conn = ag.get_conn()
    hist = load_historical(conn)

    original_profile = set_profile_overrides("football", s.edge_threshold, s.no_lineup_cap)

    # Create a custom args object to pass to agent functions
    class Args:
        pass
    
    custom_args = Args()
    custom_args.no_llm = True
    custom_args.pure_ba = s.pure_ba
    custom_args._matches_cache = []
    
    # Store the original args
    original_args = ag.GLOBAL_ARGS
    ag.GLOBAL_ARGS = custom_args

    matches = ag.fetch_backtest_matches(conn, sport="football", limit=s.limit, match_id=None)
    seen = len(matches)
    
    # Store matches in the custom args for reference
    custom_args._matches_cache = matches

    if s.league:
        matches = [m for m in matches if league_match(m.league, s.league)]

    after_league = len(matches)
    preflight_skip = 0
    ba_bypass_count = 0
    bets: List[BetRow] = []

    try:
        for match in matches:
            payload = ag.build_payload(conn, match, bankroll=bankroll)

            using_hist = False
            if match.id in hist:
                payload["known_facts"] = hist[match.id]
                setattr(match, "using_historical_features", True)
                using_hist = True

            facts = payload.get("known_facts", {})
            data_quality = ag.get_match_data_quality(conn, match.id)

            ba_ok, ba_rule = ag.is_backtest_approved(match, facts)
            live_skip_reason = ag.pre_flight_check(facts, match.sport)
            live_ok = live_skip_reason is None

            setattr(match, "is_backtest_approved", ba_ok)
            setattr(match, "ba_rule", ba_rule)
            if ba_ok and live_ok:
                shortlist_source = "live+ba"
            elif ba_ok:
                shortlist_source = "ba"
            else:
                shortlist_source = "live"
            setattr(match, "shortlist_source", shortlist_source)

            payload["is_backtest_approved"] = ba_ok
            payload["ba_rule"] = ba_rule
            payload["shortlist_source"] = shortlist_source

            if s.only_ba and not ba_ok:
                continue

            if live_skip_reason and not ba_ok:
                preflight_skip += 1
                continue

            if live_skip_reason and ba_ok:
                ba_bypass_count += 1

            rec = ag.normalize_response(ag.simulate_llm_response(payload))
            if rec.get("decision") == "PASS":
                continue

            rec = ag.calibrate_probability(rec, match, facts, data_quality)
            rec = ag.enrich_with_math(rec, match, facts)

            if rec.get("market") == "pass":
                continue

            if not apply_market_filter(rec, s.market_filter):
                continue

            valid, notes = ag.validate_recommendation(rec, payload, bankroll)
            if not valid:
                continue

            stake_pct = float(rec.get("stake_pct", 0.0) or 0.0)
            if s.max_stake_pct is not None:
                stake_pct = min(stake_pct, s.max_stake_pct)

            stake_abs = round(bankroll * stake_pct, 2)
            actual = ag._get_actual_outcome(conn, match.id)
            won = None if actual is None else (rec.get("market") == actual)

            bets.append(BetRow(
                match_id=match.id,
                league=match.league,
                home_team=match.home_team,
                away_team=match.away_team,
                market=str(rec.get("market")),
                market_label=market_label_for(rec),
                odds=float(rec.get("odds", 0.0) or 0.0),
                stake_abs=stake_abs,
                ba_rule=ba_rule,
                shortlist_source=shortlist_source,
                actual_outcome=actual,
                won=won,
                using_hist=using_hist,
            ))
    finally:
        restore_profile("football", original_profile)
        # Restore the original args
        ag.GLOBAL_ARGS = original_args
        conn.close()

    settled = [b for b in bets if b.actual_outcome]
    wins = sum(1 for b in settled if b.won is True)
    losses = sum(1 for b in settled if b.won is False)
    no_result = len(bets) - len(settled)
    staked = round(sum(b.stake_abs for b in settled), 2)
    profit = 0.0
    for b in settled:
        if b.won:
            profit += b.stake_abs * (b.odds - 1.0)
        else:
            profit -= b.stake_abs
    profit = round(profit, 2)
    roi = round((profit / staked * 100.0), 2) if staked else 0.0

    p1_count = sum(1 for b in bets if b.market_label == "П1")
    p2_count = sum(1 for b in bets if b.market_label == "П2")
    x_count = sum(1 for b in bets if b.market_label == "X")
    ba_count = sum(1 for b in bets if b.ba_rule)
    hist_bets = sum(1 for b in bets if b.using_hist)

    REPORTS.mkdir(parents=True, exist_ok=True)
    out_file = REPORTS / f"{s.name}.bets.json"
    out_file.write_text(json.dumps([asdict(b) for b in bets], ensure_ascii=False, indent=2), encoding="utf-8")

    result = ScenarioResult(
        scenario_name=s.name,
        league=s.league,
        market_filter=s.market_filter,
        only_ba=s.only_ba,
        pure_ba=s.pure_ba,
        edge_threshold=s.edge_threshold,
        no_lineup_cap=s.no_lineup_cap,
        max_stake_pct=s.max_stake_pct,
        matches_seen=seen,
        matches_after_league=after_league,
        preflight_skip=preflight_skip,
        ba_bypass_count=ba_bypass_count,
        bets=len(bets),
        settled=len(settled),
        wins=wins,
        losses=losses,
        no_result=no_result,
        staked=staked,
        profit=profit,
        roi=roi,
        p1_count=p1_count,
        p2_count=p2_count,
        x_count=x_count,
        ba_count=ba_count,
        ba_draw_sa=sum(1 for b in bets if b.ba_rule == "DRAW_SA"),
        ba_away_sa=sum(1 for b in bets if b.ba_rule == "AWAY_SA"),
        ba_p1_pd=sum(1 for b in bets if b.ba_rule == "P1_PD"),
        ba_draw_bl1_fl1=sum(1 for b in bets if b.ba_rule == "DRAW_BL1_FL1"),
        ba_away_bl1=sum(1 for b in bets if b.ba_rule == "AWAY_BL1"),
        hist_bets=hist_bets,
        output_file=str(out_file),
        bets_file=str(out_file),
    )
    return result, bets


def save_reports(results: List[ScenarioResult]) -> Dict[str, str]:
    REPORTS.mkdir(parents=True, exist_ok=True)

    json_path = REPORTS / "matrix_results.json"
    csv_path = REPORTS / "matrix_results.csv"
    txt_path = REPORTS / "matrix_summary.txt"

    json_path.write_text(
        json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))

    lines: List[str] = []
    lines.append("BACKTEST MATRIX SUMMARY")
    lines.append("=" * 100)
    lines.append("NOTE: roles are intentionally excluded (no historical roles dataset yet)")
    lines.append("")

    ranked = sorted(results, key=lambda x: (x.roi, x.profit, -x.bets), reverse=True)
    for r in ranked:
        lines.append(f"Scenario: {r.scenario_name}")
        lines.append(f"  league           : {r.league}")
        lines.append(f"  market_filter    : {r.market_filter}")
        lines.append(f"  only_ba          : {r.only_ba}")
        lines.append(f"  pure_ba          : {r.pure_ba}")
        lines.append(f"  edge_threshold   : {r.edge_threshold}")
        lines.append(f"  no_lineup_cap    : {r.no_lineup_cap}")
        lines.append(f"  max_stake_pct    : {r.max_stake_pct}")
        lines.append(f"  matches_seen     : {r.matches_seen}")
        lines.append(f"  matches_after_league: {r.matches_after_league}")
        lines.append(f"  preflight_skip   : {r.preflight_skip}")
        lines.append(f"  ba_bypass_count  : {r.ba_bypass_count}")
        lines.append(f"  bets             : {r.bets}")
        lines.append(f"  settled          : {r.settled}")
        lines.append(f"  wins/losses      : {r.wins}/{r.losses}")
        lines.append(f"  no_result        : {r.no_result}")
        lines.append(f"  staked/profit    : {r.staked} / {r.profit}")
        lines.append(f"  roi              : {r.roi}%")
        lines.append(f"  markets P1/P2/X  : {r.p1_count}/{r.p2_count}/{r.x_count}")
        lines.append(f"  BA total         : {r.ba_count}")
        lines.append(
            f"  BA rules         : DRAW_SA={r.ba_draw_sa}, AWAY_SA={r.ba_away_sa}, "
            f"P1_PD={r.ba_p1_pd}, DRAW_BL1_FL1={r.ba_draw_bl1_fl1}, AWAY_BL1={r.ba_away_bl1}"
        )
        lines.append(f"  HIST bets        : {r.hist_bets}")
        lines.append(f"  bets file        : {r.bets_file}")
        lines.append("-" * 100)

    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "csv": str(csv_path), "txt": str(txt_path)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--bankroll", type=float, default=100000.0)
    ap.add_argument("--quick", action="store_true", help="Run a small starter subset")
    args = ap.parse_args()

    scenarios = deepcopy(QUICK_SCENARIOS if args.quick else STARTER_SCENARIOS)
    for sc in scenarios:
        sc.limit = args.limit if sc.limit == 2000 else sc.limit

    results: List[ScenarioResult] = []
    for sc in scenarios:
        print(f"Running {sc.scenario_name if hasattr(sc, 'scenario_name') else sc.name}...")
        result, _ = run_scenario(sc, args.bankroll)
        results.append(result)
        print(f"  ROI={result.roi}% | bets={result.bets} | wins/losses={result.wins}/{result.losses}")

    paths = save_reports(results)
    print("\nSaved reports:")
    for k, v in paths.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
