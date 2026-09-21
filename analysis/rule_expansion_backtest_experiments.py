#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RULE EXPANSION BACKTEST EXPERIMENTS — SANDBOX ONLY

This script is a SEPARATE experimental analysis tool.
It does NOT modify any production files, live rules, or existing backtest configs.

Purpose: Test expanded rule parameter variants against historical data
to see if they increase volume without destroying ROI.

Usage:
  python analysis/rule_expansion_backtest_experiments.py
  python analysis/rule_expansion_backtest_experiments.py --rule BTTS_YES_CORE
  python analysis/rule_expansion_backtest_experiments.py --rule ALL --verbose
"""
import sqlite3, os, sys, json, math
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
BANK = float(os.getenv("BETAGENT_BANK", "100000"))


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def kelly_quarter(our_p: float, odds: float) -> float:
    k = (our_p * odds - 1) / (odds - 1)
    return max(0.0, k * 0.25)


def run_backtest_variant(conn, league_sql: str, check_fn, probability: float,
                         market: str, bank: float = 100000, min_ev: float = 0.03):
    """
    Run a backtest for a single rule variant.
    check_fn(row_dict) -> bool: whether the match qualifies for this rule variant.
    probability: our estimated probability for this market (fixed per rule).
    Returns both Kelly-compounding and flat-staking metrics.
    """
    query = f"""
        SELECT * FROM backtest_matches
        WHERE {league_sql}
          AND result IS NOT NULL AND result != ''
          AND odds_home > 0 AND odds_draw > 0 AND odds_away > 0
        ORDER BY match_date ASC
    """
    rows = conn.execute(query).fetchall()

    current_bank = bank
    flat_stake = bank * 0.01  # 1% flat stake
    flat_bank = bank
    bets = []

    for row in rows:
        rd = dict(row)
        if not check_fn(rd):
            continue

        # Get odds for the target market
        odds_map = {
            "home": rd.get("odds_home"),
            "draw": rd.get("odds_draw"),
            "away": rd.get("odds_away"),
            "btts_yes": rd.get("odds_btts_yes"),
            "over_2_5": rd.get("odds_over_2_5"),
        }
        odds = odds_map.get(market)
        if odds is None or odds <= 1.0:
            continue

        our_p = probability
        ev = our_p * odds - 1
        if ev < min_ev:
            continue

        kelly = kelly_quarter(our_p, odds)
        if kelly <= 0:
            continue

        stake_pct = min(kelly, 0.05)  # max 5% bank
        stake = current_bank * stake_pct
        if stake < 100:
            continue

        # Determine result
        result_map = {"H": "home", "D": "draw", "A": "away"}
        actual = result_map.get(rd["result"])
        won = (actual == market) if market in ("home", "draw", "away") else None

        # For BTTS and totals, check actual goals
        if market == "btts_yes":
            hs = rd.get("home_score")
            aw = rd.get("away_score")
            won = (hs is not None and aw is not None and hs > 0 and aw > 0)
        elif market == "over_2_5":
            hs = rd.get("home_score")
            aw = rd.get("away_score")
            won = (hs is not None and aw is not None and (hs + aw) > 2.5)

        if won is None:
            continue

        profit = stake * (odds - 1) if won else -stake
        current_bank += profit

        # Flat staking
        flat_profit = flat_stake * (odds - 1) if won else -flat_stake
        flat_bank += flat_profit

        bets.append({
            "date": rd["match_date"],
            "season": rd["season"],
            "home": rd["home_team"],
            "away": rd["away_team"],
            "league": rd["league"],
            "market": market,
            "odds": odds,
            "stake": stake,
            "stake_pct": stake_pct,
            "won": won,
            "profit": profit,
            "bank_after": current_bank,
            "ev": ev,
            "flat_profit": flat_profit,
            "flat_bank_after": flat_bank,
        })

    return compute_metrics(bets, bank)


def compute_metrics(bets: List[dict], initial_bank: float) -> dict:
    if not bets:
        return {"bets": 0}

    wins = sum(1 for b in bets if b["won"])
    losses = len(bets) - wins
    total_staked = sum(b["stake"] for b in bets)
    total_profit = sum(b["profit"] for b in bets)
    roi = total_profit / total_staked * 100 if total_staked > 0 else 0
    winrate = wins / len(bets) * 100
    avg_odds = sum(b["odds"] for b in bets) / len(bets)

    # Flat staking metrics
    flat_total_staked = sum(b.get("flat_profit", 0) + (b["stake"] if not b["won"] else 0) for b in bets)
    flat_total_profit = sum(b["flat_profit"] for b in bets)
    flat_roi = flat_total_profit / (len(bets) * initial_bank * 0.01) * 100 if bets else 0

    # Yearly breakdown
    yearly = {}
    for b in bets:
        year = b["date"][:4]
        if year not in yearly:
            yearly[year] = {"bets": 0, "wins": 0, "staked": 0, "profit": 0, "flat_profit": 0}
        yearly[year]["bets"] += 1
        if b["won"]:
            yearly[year]["wins"] += 1
        yearly[year]["staked"] += b["stake"]
        yearly[year]["profit"] += b["profit"]
        yearly[year]["flat_profit"] += b.get("flat_profit", 0)

    for y in yearly:
        d = yearly[y]
        d["winrate"] = d["wins"] / d["bets"] * 100 if d["bets"] > 0 else 0
        d["roi"] = d["profit"] / d["staked"] * 100 if d["staked"] > 0 else 0
        d["flat_roi"] = d["flat_profit"] / (d["bets"] * initial_bank * 0.01) * 100 if d["bets"] > 0 else 0

    # 2024-2026 and 2025-2026 aggregates
    def period_stats(start_year: str, end_year: str):
        pb = [b for b in bets if start_year <= b["date"][:4] <= end_year]
        if not pb:
            return 0, 0, 0, 0
        ps = sum(b["stake"] for b in pb)
        pp = sum(b["profit"] for b in pb)
        pw = sum(1 for b in pb if b["won"])
        fp = sum(b.get("flat_profit", 0) for b in pb)
        f_roi = fp / (len(pb) * initial_bank * 0.01) * 100 if pb else 0
        return pp / ps * 100 if ps > 0 else 0, pw / len(pb) * 100, len(pb), f_roi

    roi_2426, wr_2426, n_2426, flat_2426 = period_stats("2024", "2026")
    roi_2526, wr_2526, n_2526, flat_2526 = period_stats("2025", "2026")

    # Max drawdown — track running bank from initial_bank
    running_bank = initial_bank
    peak = initial_bank
    max_dd = 0.0
    for b in bets:
        running_bank += b["profit"]
        if running_bank > peak:
            peak = running_bank
        dd = (peak - running_bank) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Longest losing streak
    max_ls = 0
    cur_ls = 0
    for b in bets:
        if not b["won"]:
            cur_ls += 1
            if cur_ls > max_ls:
                max_ls = cur_ls
        else:
            cur_ls = 0

    # Bets per month
    months = set()
    for b in bets:
        months.add(b["date"][:7])
    n_months = max(len(months), 1)
    bets_per_month = len(bets) / n_months

    return {
        "bets": len(bets),
        "wins": wins,
        "losses": losses,
        "winrate": winrate,
        "total_staked": round(total_staked, 2),
        "total_profit": round(total_profit, 2),
        "roi": round(roi, 2),
        "avg_odds": round(avg_odds, 2),
        "final_bank": round(running_bank, 2),
        "bank_growth": round((running_bank - initial_bank) / initial_bank * 100, 2),
        "bets_per_month": round(bets_per_month, 1),
        "max_drawdown_pct": round(max_dd, 1),
        "longest_losing_streak": max_ls,
        "flat_total_profit": round(flat_total_profit, 2),
        "flat_roi": round(flat_roi, 2),
        "yearly": yearly,
        "roi_2024_2026": round(roi_2426, 2),
        "wr_2024_2026": round(wr_2426, 1),
        "n_2024_2026": n_2426,
        "flat_2024_2026": round(flat_2426, 2),
        "roi_2025_2026": round(roi_2526, 2),
        "wr_2025_2026": round(wr_2526, 1),
        "n_2025_2026": n_2526,
        "flat_2025_2026": round(flat_2526, 2),
    }


# ============================================================
# EMPIRICAL PROBABILITY ESTIMATION
# ============================================================

def estimate_empirical_probability(conn, league_sql: str, check_fn, market: str) -> float:
    """
    Estimate the true probability of a market outcome from historical data
    for matches that pass the baseline check. This gives us a realistic
    probability to use in the backtest instead of hardcoded values.
    """
    query = f"""
        SELECT * FROM backtest_matches
        WHERE {league_sql}
          AND result IS NOT NULL AND result != ''
          AND odds_home > 0 AND odds_draw > 0 AND odds_away > 0
        ORDER BY match_date ASC
    """
    rows = conn.execute(query).fetchall()

    total = 0
    hits = 0
    for row in rows:
        rd = dict(row)
        if not check_fn(rd):
            continue
        odds_map = {
            "home": rd.get("odds_home"),
            "draw": rd.get("odds_draw"),
            "away": rd.get("odds_away"),
            "btts_yes": rd.get("odds_btts_yes"),
            "over_2_5": rd.get("odds_over_2_5"),
        }
        odds = odds_map.get(market)
        if odds is None or odds <= 1.0:
            continue

        if market == "btts_yes":
            hs = rd.get("home_score")
            aw = rd.get("away_score")
            hit = (hs is not None and aw is not None and hs > 0 and aw > 0)
        elif market == "over_2_5":
            hs = rd.get("home_score")
            aw = rd.get("away_score")
            hit = (hs is not None and aw is not None and (hs + aw) > 2.5)
        elif market == "draw":
            hit = (rd["result"] == "D")
        else:
            continue

        total += 1
        if hit:
            hits += 1

    return hits / total if total > 0 else 0.0


# ============================================================
# CHECK FUNCTIONS — replicate rule logic on backtest_matches
# ============================================================

def _btts_core_check(r, epl_min, bl1_min, btts_max):
    """BTTS_YES_CORE check with configurable odds range.
    Baseline: EPL 2.00-2.10, BL1 1.95-2.10
    Form checks (scored>=1.0, conceded>=0.8) are skipped in backtest
    since form_details aren't available in backtest_matches.
    """
    league = r.get("league", "")
    btts = r.get("odds_btts_yes")
    if btts is None:
        return False

    if league == "EPL":
        return epl_min <= btts <= btts_max
    elif league == "BL1":
        return bl1_min <= btts <= btts_max
    return False


def _pd_btts_check(r, o25_min, o25_max, btts_min, btts_max):
    """PD_BTTS_DOUBLE check with configurable odds ranges.
    Baseline: over25 1.6-1.9, btts 1.75-1.95
    """
    o25 = r.get("odds_over_2_5")
    btts = r.get("odds_btts_yes")
    if o25 is None or btts is None:
        return False
    return (o25_min <= o25 <= o25_max) and (btts_min <= btts <= btts_max)


def _fl1_btts_check(r, o25_min, o25_max, btts_min, btts_max):
    """FL1_BTTS_DOUBLE check with configurable odds ranges.
    Baseline: over25 1.6-1.9, btts 2.0-2.1
    """
    o25 = r.get("odds_over_2_5")
    btts = r.get("odds_btts_yes")
    if o25 is None or btts is None:
        return False
    return (o25_min <= o25 <= o25_max) and (btts_min <= btts <= btts_max)


def _draw_sa_check(r, max_goals, max_conceded, max_td, max_fg):
    """DRAW_SA check with configurable thresholds.
    Baseline: draw 3.0-3.85, goals<=1.55, conceded<=1.75, td<=5, fg<=3
    Table diff and form gap checks are skipped in backtest since
    position/form data isn't in backtest_matches.
    The goals/conceded thresholds ARE applied if we can use them,
    but backtest_matches doesn't have those columns either.
    So we apply only the odds filter + configurable thresholds
    that are available.
    """
    od = r.get("odds_draw")
    if od is None:
        return False
    if not (3.0 <= od <= 3.85):
        return False
    # backtest_matches doesn't have goals_avg or conceded_avg columns,
    # nor table positions or form. The only filter we can apply is odds.
    # This is a known limitation — the real live rule is stricter.
    # We note this in the report.
    return True


def _summer_btts_check(r, leagues, teams_dict, btts_min, btts_max):
    """SUMMER_BTTS_HOME check with configurable leagues and odds.
    Baseline: DNK/SWE/FIN, specific teams, btts 1.55-1.85, months 4-11.
    """
    league = r.get("league", "")
    if league not in leagues:
        return False

    btts = r.get("odds_btts_yes")
    if btts is None:
        return False
    if not (btts_min <= btts <= btts_max):
        return False

    # Team check — if teams_dict[league] is empty, skip team filter for that league
    teams = teams_dict.get(league, [])
    if teams:
        home = (r.get("home_team") or "")
        if not any(t in home for t in teams):
            return False

    # Month filter (April-November)
    md = r.get("match_date", "")
    if md:
        try:
            month = int(md.split("-")[1])
            if not (4 <= month <= 11):
                return False
        except (ValueError, IndexError):
            pass

    return True


# ============================================================
# RULE VARIANT DEFINITIONS
# ============================================================

def define_variants():
    """Returns dict of rule_name -> {league_filter, market, variants}"""
    return {
        "BTTS_YES_CORE": {
            "league_sql": "league IN ('EPL', 'BL1')",
            "league_name": "EPL / BL1",
            "market": "btts_yes",
            "variants": {
                "baseline": {
                    "desc": "EPL: 2.00-2.10, BL1: 1.95-2.10",
                    "check": lambda r: _btts_core_check(r, 2.00, 1.95, 2.10),
                },
                "exp_1_80_2_15": {
                    "desc": "EPL: 1.80-2.15, BL1: 1.80-2.15 (wide expansion)",
                    "check": lambda r: _btts_core_check(r, 1.80, 1.80, 2.15),
                },
                "exp_1_80_2_05": {
                    "desc": "EPL: 1.80-2.05, BL1: 1.80-2.05 (tight upper)",
                    "check": lambda r: _btts_core_check(r, 1.80, 1.80, 2.05),
                },
                "exp_1_75_2_15": {
                    "desc": "EPL: 1.75-2.15, BL1: 1.75-2.15 (widest)",
                    "check": lambda r: _btts_core_check(r, 1.75, 1.75, 2.15),
                },
            },
        },
        "PD_BTTS_DOUBLE": {
            "league_sql": "league = 'PD'",
            "league_name": "La Liga",
            "market": "btts_yes",
            "variants": {
                "baseline": {
                    "desc": "over25: 1.6-1.9, btts: 1.75-1.95",
                    "check": lambda r: _pd_btts_check(r, 1.6, 1.9, 1.75, 1.95),
                },
                "exp_wide": {
                    "desc": "over25: 1.5-2.0, btts: 1.70-2.00 (wide)",
                    "check": lambda r: _pd_btts_check(r, 1.5, 2.0, 1.70, 2.00),
                },
                "exp_moderate": {
                    "desc": "over25: 1.55-2.05, btts: 1.70-2.05 (moderate)",
                    "check": lambda r: _pd_btts_check(r, 1.55, 2.05, 1.70, 2.05),
                },
                "exp_conservative": {
                    "desc": "over25: 1.55-1.95, btts: 1.70-2.00 (conservative)",
                    "check": lambda r: _pd_btts_check(r, 1.55, 1.95, 1.70, 2.00),
                },
            },
        },
        "FL1_BTTS_DOUBLE": {
            "league_sql": "league = 'FL1'",
            "league_name": "Ligue 1",
            "market": "btts_yes",
            "variants": {
                "baseline": {
                    "desc": "over25: 1.6-1.9, btts: 2.0-2.1",
                    "check": lambda r: _fl1_btts_check(r, 1.6, 1.9, 2.0, 2.1),
                },
                "exp_wide": {
                    "desc": "over25: 1.5-2.15, btts: 1.95-2.15 (wide)",
                    "check": lambda r: _fl1_btts_check(r, 1.5, 2.15, 1.95, 2.15),
                },
                "exp_moderate": {
                    "desc": "over25: 1.5-2.10, btts: 1.95-2.15 (moderate)",
                    "check": lambda r: _fl1_btts_check(r, 1.5, 2.10, 1.95, 2.15),
                },
                "exp_conservative": {
                    "desc": "over25: 1.55-2.0, btts: 1.95-2.12 (conservative)",
                    "check": lambda r: _fl1_btts_check(r, 1.55, 2.0, 1.95, 2.12),
                },
            },
        },
        "DRAW_SA": {
            "league_sql": "league = 'SA'",
            "league_name": "Serie A",
            "market": "draw",
            "variants": {
                "baseline": {
                    "desc": "draw 3.0-3.85 (no form/table in backtest data)",
                    "check": lambda r: _draw_sa_check(r, 1.55, 1.75, 5, 3),
                },
                "exp_moderate": {
                    "desc": "draw 3.0-3.85, goals<=1.75, conceded<=2.0 (moderate — goals filter not available in backtest)",
                    "check": lambda r: _draw_sa_check(r, 1.75, 2.0, 7, 4),
                },
                "exp_conservative": {
                    "desc": "draw 3.0-3.85, goals<=1.65, conceded<=1.85 (conservative — goals filter not available in backtest)",
                    "check": lambda r: _draw_sa_check(r, 1.65, 1.85, 6, 3),
                },
            },
        },
        "SUMMER_BTTS_HOME": {
            "league_sql": "league IN ('DNK', 'SWE', 'FIN')",
            "league_name": "DNK / SWE / FIN",
            "market": "btts_yes",
            "variants": {
                "baseline": {
                    "desc": "DNK: Виборг/Оденсе/Норшелланн, SWE: Хеккен, FIN: СИК/Хака, btts 1.55-1.85",
                    "check": lambda r: _summer_btts_check(r, ["DNK", "SWE", "FIN"],
                        {"DNK": ["Виборг", "Оденсе", "Норшелланн"],
                         "SWE": ["Хеккен"],
                         "FIN": ["СИК", "Хака"]},
                        1.55, 1.85),
                },
                "exp_add_nor_irl": {
                    "desc": "baseline + NOR/IRL leagues with ALL teams (no team filter for new leagues)",
                    "league_sql": "league IN ('DNK', 'SWE', 'FIN', 'NOR', 'IRL')",
                    "check": lambda r: _summer_btts_check(r, ["DNK", "SWE", "FIN", "NOR", "IRL"],
                        {"DNK": ["Виборг", "Оденсе", "Норшелланн"],
                         "SWE": ["Хеккен"],
                         "FIN": ["СИК", "Хака"],
                         "NOR": [],
                         "IRL": []},
                        1.55, 1.85),
                },
                "exp_wide_odds": {
                    "desc": "baseline teams + btts 1.50-1.90 (wider odds)",
                    "check": lambda r: _summer_btts_check(r, ["DNK", "SWE", "FIN"],
                        {"DNK": ["Виборг", "Оденсе", "Норшелланн"],
                         "SWE": ["Хеккен"],
                         "FIN": ["СИК", "Хака"]},
                        1.50, 1.90),
                },
            },
        },
    }


# ============================================================
# MAIN EXPERIMENT RUNNER
# ============================================================

def run_experiments(target_rule: Optional[str] = None, verbose: bool = False):
    conn = get_conn()
    variants = define_variants()

    if target_rule and target_rule != "ALL":
        variants = {target_rule: variants[target_rule]}

    results = {}

    for rule_name, rule_def in variants.items():
        print(f"\n{'='*70}")
        print(f"  {rule_name} ({rule_def['league_name']})")
        print(f"  Market: {rule_def['market']}")
        print(f"{'='*70}")

        rule_results = {}

        # First, estimate empirical probability from baseline variant
        baseline_check = rule_def["variants"]["baseline"]["check"]
        emp_prob = estimate_empirical_probability(
            conn, rule_def["league_sql"], baseline_check, rule_def["market"]
        )
        print(f"  Empirical probability (baseline): {emp_prob:.4f}")

        for variant_name, variant_def in rule_def["variants"].items():
            is_baseline = variant_name == "baseline"
            label = "BASELINE" if is_baseline else variant_name

            print(f"\n  [{label}] {variant_def['desc']}")

            # Use variant-specific league_sql if provided, otherwise default
            league_sql = variant_def.get("league_sql", rule_def["league_sql"])

            metrics = run_backtest_variant(
                conn,
                league_sql,
                variant_def["check"],
                emp_prob,
                rule_def["market"],
            )

            if metrics["bets"] == 0:
                print(f"    -> 0 bets")
                rule_results[variant_name] = {**metrics, "desc": variant_def["desc"]}
                continue

            icon = "OK" if metrics["roi"] >= 4 else ("WARN" if metrics["roi"] >= 0 else "BAD")
            print(f"    -> {metrics['bets']} bets | W:{metrics['wins']} L:{metrics['losses']} | "
                  f"WR: {metrics['winrate']:.1f}% | [{icon}] ROI: {metrics['roi']:+.2f}% | "
                  f"PnL: {metrics['total_profit']:+,.0f} | "
                  f"DD: {metrics['max_drawdown_pct']:.1f}% | LS: {metrics['longest_losing_streak']}")

            rule_results[variant_name] = {**metrics, "desc": variant_def["desc"]}

        results[rule_name] = rule_results

    conn.close()
    return results


def generate_report(results: dict):
    """Generate markdown report from experiment results."""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = []
    lines.append(f"# Rule Expansion Backtest Experiments — {today}\n")
    lines.append("## Sandbox Experiment — NO production changes\n")
    lines.append("This report tests expanded parameter variants for existing rule-driven strategies.")
    lines.append("All experiments run against historical `backtest_matches` data.")
    lines.append("Production rules are NOT modified.\n")
    lines.append("**Important:** Probability for each rule is estimated empirically from the baseline")
    lines.append("variant's historical hit rate on the backtest data. This is then applied uniformly")
    lines.append("across all variants of that rule for fair comparison.\n")
    lines.append("**Limitation:** `backtest_matches` does not contain form details, table positions,")
    lines.append("or goal averages. Rules that depend on these (DRAW_SA goals/table filters,")
    lines.append("BTTS_YES_CORE form filters) are tested with only their odds-range criteria.")
    lines.append("This means the backtest is more permissive than live rules.\n")

    lines.append("---\n")
    lines.append("## 1. Baseline vs Variants — Summary Table\n")

    for rule_name, rule_results in results.items():
        lines.append(f"\n### {rule_name}\n")

        lines.append("| Variant | Bets | WR% | ROI% | Flat ROI% | Flat PnL | Avg Odds | Bets/Mo | Max DD% | Max LS |")
        lines.append("|---------|------|-----|------|-----------|----------|----------|---------|---------|--------|")

        for vname, vdata in rule_results.items():
            if vdata["bets"] == 0:
                lines.append(f"| {vname} | 0 | - | - | - | - | - | - | - | - |")
                continue
            lines.append(
                f"| {vname} | {vdata['bets']} | {vdata['winrate']:.1f} | "
                f"{vdata['roi']:+.2f}% | {vdata.get('flat_roi', 0):+.2f}% | "
                f"{vdata.get('flat_total_profit', 0):+,.0f} | "
                f"{vdata['avg_odds']:.2f} | {vdata['bets_per_month']:.1f} | "
                f"{vdata['max_drawdown_pct']:.1f} | {vdata['longest_losing_streak']} |"
            )

        # Verdict
        lines.append(f"\n**Verdict:** {_get_verdict(rule_results)}\n")

    lines.append("---\n")
    lines.append("## 2. Yearly Breakdown\n")

    for rule_name, rule_results in results.items():
        lines.append(f"\n### {rule_name}\n")
        for vname, vdata in rule_results.items():
            if vdata["bets"] == 0 or "yearly" not in vdata:
                continue
            lines.append(f"\n**{vname}:**\n")
            lines.append("| Year | Bets | Wins | WR% | ROI% | Flat ROI% | PnL |")
            lines.append("|------|------|------|-----|------|-----------|-----|")
            for year in sorted(vdata["yearly"].keys()):
                y = vdata["yearly"][year]
                lines.append(
                    f"| {year} | {y['bets']} | {y['wins']} | "
                    f"{y['winrate']:.1f}% | {y['roi']:+.2f}% | "
                    f"{y.get('flat_roi', 0):+.2f}% | {y['profit']:+,.0f} |"
                )

    lines.append("---\n")
    lines.append("## 3. 2024-2026 vs 2025-2026 Comparison\n")

    lines.append("| Rule | Variant | ROI 24-26 | Flat 24-26 | WR 24-26 | N 24-26 | ROI 25-26 | Flat 25-26 | WR 25-26 | N 25-26 |")
    lines.append("|------|---------|-----------|------------|----------|---------|-----------|------------|----------|---------|")

    for rule_name, rule_results in results.items():
        for vname, vdata in rule_results.items():
            if vdata["bets"] == 0:
                continue
            lines.append(
                f"| {rule_name} | {vname} | "
                f"{vdata.get('roi_2024_2026', 0):+.2f}% | "
                f"{vdata.get('flat_2024_2026', 0):+.2f}% | "
                f"{vdata.get('wr_2024_2026', 0):.1f}% | "
                f"{vdata.get('n_2024_2026', 0)} | "
                f"{vdata.get('roi_2025_2026', 0):+.2f}% | "
                f"{vdata.get('flat_2025_2026', 0):+.2f}% | "
                f"{vdata.get('wr_2025_2026', 0):.1f}% | "
                f"{vdata.get('n_2025_2026', 0)} |"
            )

    lines.append("---\n")
    lines.append("## 4. Drawdown & Losing Streak Comparison\n")

    lines.append("| Rule | Variant | Max DD% | Max LS | Bets/Mo | ROI% | Verdict |")
    lines.append("|------|---------|---------|--------|---------|------|---------|")

    for rule_name, rule_results in results.items():
        for vname, vdata in rule_results.items():
            if vdata["bets"] == 0:
                continue
            verdict = _single_verdict(vdata, rule_results.get("baseline", {}))
            lines.append(
                f"| {rule_name} | {vname} | "
                f"{vdata['max_drawdown_pct']:.1f}% | "
                f"{vdata['longest_losing_streak']} | "
                f"{vdata['bets_per_month']:.1f} | "
                f"{vdata['roi']:+.2f}% | "
                f"{verdict} |"
            )

    lines.append("---\n")
    lines.append("## 5. Final Verdicts\n")

    for rule_name, rule_results in results.items():
        baseline = rule_results.get("baseline", {})
        lines.append(f"\n### {rule_name}\n")

        if baseline.get("bets", 0) == 0:
            lines.append(f"**Baseline: 0 bets** — rule produces no signals on backtest data.\n")
            lines.append("Cannot evaluate expansions without a working baseline.\n")
            continue

        lines.append(f"**Baseline:** {baseline['bets']} bets, WR {baseline['winrate']:.1f}%, "
                     f"ROI {baseline['roi']:+.2f}%, Flat ROI {baseline.get('flat_roi', 0):+.2f}%, "
                     f"Flat PnL {baseline.get('flat_total_profit', 0):+,.0f}\n")

        for vname, vdata in rule_results.items():
            if vname == "baseline":
                continue
            if vdata["bets"] == 0:
                lines.append(f"- **{vname}:** 0 bets — too restrictive\n")
                continue

            verdict = _single_verdict(vdata, baseline)
            delta_bets = vdata["bets"] - baseline["bets"]
            delta_roi = vdata["roi"] - baseline["roi"]
            delta_flat = vdata.get("flat_roi", 0) - baseline.get("flat_roi", 0)

            lines.append(f"- **{vname}:** {vdata['bets']} bets ({delta_bets:+d}), "
                         f"ROI {vdata['roi']:+.2f}% ({delta_roi:+.2f}), "
                         f"Flat ROI {vdata.get('flat_roi', 0):+.2f}% ({delta_flat:+.2f}), "
                         f"Flat PnL {vdata.get('flat_total_profit', 0):+,.0f} -> **{verdict}**\n")

    lines.append("---\n")
    lines.append("## Methodology Notes\n")
    lines.append("- All experiments use `backtest_matches` table (historical data from football-data.co.uk)")
    lines.append("- Kelly quarter-staking with 5% max cap")
    lines.append("- Minimum EV: 0.03")
    lines.append("- Minimum stake: 100 RUB")
    lines.append("- Probability estimated empirically from baseline variant's historical hit rate")
    lines.append("- NO production rules were modified")
    lines.append("- NO live parameters were changed")
    lines.append("- This is a sandbox analysis only\n")

    return "\n".join(lines)


def _get_verdict(rule_results: dict) -> str:
    baseline = rule_results.get("baseline", {})
    if baseline.get("bets", 0) == 0:
        return "No baseline — cannot evaluate"

    verdicts = []
    for vname, vdata in rule_results.items():
        if vname == "baseline" or vdata["bets"] == 0:
            continue
        v = _single_verdict(vdata, baseline)
        verdicts.append(f"{vname}={v}")
    return "; ".join(verdicts) if verdicts else "No variants with bets"


def _single_verdict(vdata: dict, baseline: dict) -> str:
    """Determine verdict for a single variant vs baseline.
    Uses flat ROI for comparison since Kelly-compounding distorts
    ROI over large bet counts.
    """
    if vdata["bets"] == 0:
        return "REJECT (no bets)"

    if baseline.get("bets", 0) == 0:
        return "REJECT (no baseline)"

    delta_bets = vdata["bets"] - baseline["bets"]
    flat_roi = vdata.get("flat_roi", 0)
    base_flat = baseline.get("flat_roi", 0)
    delta_flat = flat_roi - base_flat

    # REJECT conditions
    if flat_roi < 0 and base_flat > 0:
        return "REJECT (ROI turned negative)"
    if base_flat > 0 and flat_roi < base_flat * 0.5:
        return "REJECT (ROI destroyed >50%)"
    if vdata["max_drawdown_pct"] > 30 and baseline["max_drawdown_pct"] < 20:
        return "REJECT (drawdown too high)"
    if delta_flat < -5:
        return "REJECT (ROI drop >5pp)"

    # LIVE TRIAL CANDIDATE conditions
    if (delta_bets > baseline["bets"] * 0.3 and  # 30%+ more bets
            flat_roi > 0 and
            delta_flat > -3):  # ROI drop < 3pp
        return "LIVE TRIAL CANDIDATE"

    # WATCHLIST conditions
    if flat_roi > 0 and delta_bets > 0:
        return "WATCHLIST"

    return "WATCHLIST"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", default="ALL", help="Specific rule or ALL")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    results = run_experiments(args.rule, args.verbose)

    # Save JSON
    def serialize(obj):
        if isinstance(obj, dict):
            return {k: serialize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [serialize(v) for v in obj]
        return obj

    with open("analysis/rule_expansion_data.json", "w") as f:
        json.dump(serialize(results), f, ensure_ascii=False, indent=2, default=str)

    # Generate and save report
    report = generate_report(results)
    with open("analysis/rule_expansion_backtest_experiments.md", "w") as f:
        f.write(report)

    print(f"\n\nReport saved to analysis/rule_expansion_backtest_experiments.md")
    print(f"Data saved to analysis/rule_expansion_data.json")
