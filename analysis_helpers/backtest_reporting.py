#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — analysis_helpers/backtest_reporting.py

Pure helper functions for:
- Backtest settlement (score extraction, market resolution)
- Equity/streak metrics
- Strategy bucketing & statistics
- Summary printing

No DB, no orchestration, no LLM calls.
Extracted from agent_handoff_v7.py Step 3 (2026-04-14).
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional


# ============================================================
# SHADOW DETECTION
# ============================================================

def is_shadow_recommendation(rec: Dict[str, Any]) -> bool:
    """
    True если рекомендация относится к heuristic/shadow path.
    """
    if not rec:
        return False

    if rec.get("shadow_only"):
        return True

    market_error = str(rec.get("market_error") or "")
    market_error_summary = str(rec.get("market_error_summary") or "")
    strategy_name = str(rec.get("strategy_name") or "")
    strategy_family = str(rec.get("strategy_family") or "")
    live_rule_family = str(rec.get("live_rule_family") or "")

    shadow_markers = [
        "Heuristic fallback without LLM",
        "heuristic fallback",
        "shadow mode",
        "heuristic_shadow",
    ]

    blob = " | ".join([
        market_error,
        market_error_summary,
        strategy_name,
        strategy_family,
        live_rule_family,
    ]).lower()

    return any(x.lower() in blob for x in shadow_markers)


# ============================================================
# STRATEGY BUCKETING
# ============================================================

def get_strategy_bucket(match: "Match", rec: Dict[str, Any], detect_league_key_fn=None) -> str:
    """
    Нормализованный ключ стратегии для итоговой сводки.
    """
    sport = (match.sport or "unknown").lower()
    league_key = detect_league_key_fn(match.league) if detect_league_key_fn else (match.league or "unknown")

    rule = rec.get("live_rule_family")
    strategy_name = rec.get("strategy_name")
    strategy_family = rec.get("strategy_family")
    market_error_summary = str(rec.get("market_error_summary") or "")
    market_error = str(rec.get("market_error") or "")

    strat = None

    if rule:
        strat = str(rule)
    elif strategy_name:
        strat = str(strategy_name)
    elif strategy_family:
        strat = str(strategy_family)
    elif market_error_summary.startswith("Rule-driven:"):
        strat = market_error_summary.split(":", 1)[1].strip()
    elif market_error.startswith("Hockey strategy "):
        tmp = market_error.replace("Hockey strategy ", "", 1)
        strat = tmp.split(":", 1)[0].strip()
    elif rec.get("shadow_only") or "Heuristic fallback without LLM" in market_error:
        strat = "heuristic_shadow"
    elif rec.get("rule_driven"):
        strat = f"rule_driven:{rec.get('market', 'unknown')}"
    else:
        return None  # LLM DISABLED

    return f"{sport} | {league_key} | {strat}"


# ============================================================
# BACKTEST SETTLEMENT HELPERS
# ============================================================

def _extract_score_pair(match: "Match"):
    """
    Пытаемся достать счёт из backtest-матча.
    Поддерживаем разные возможные имена полей.
    """
    candidate_pairs = [
        ("rt_home_score", "rt_away_score"),  # RT first for hockey
        ("home_score", "away_score"),
        ("ft_home_score", "ft_away_score"),
        ("score_home", "score_away"),
    ]

    for h_name, a_name in candidate_pairs:
        hs = getattr(match, h_name, None)
        aw = getattr(match, a_name, None)
        if hs is not None and aw is not None:
            try:
                return int(hs), int(aw)
            except Exception:
                pass

    return None, None


def resolve_actual_market_from_match(match: "Match", rec: Dict[str, Any]) -> Optional[str]:
    """
    Возвращает фактический рынок для конкретной рекомендации:
    home / away / draw / btts_yes / btts_no
    """
    market = rec.get("market")

    # 1X2 через готовый result field
    for attr in ("result_1x2_rt", "result_1x2", "actual_result", "market_result"):
        val = getattr(match, attr, None)
        if val is not None:
            v = str(val).strip().upper()
            if market in ("home", "away", "draw"):
                if v == "H":
                    return "home"
                if v == "A":
                    return "away"
                if v == "D":
                    return "draw"

    hs, aw = _extract_score_pair(match)
    if hs is None or aw is None:
        return None

    # 1X2
    if market in ("home", "away", "draw"):
        if hs > aw:
            return "home"
        if aw > hs:
            return "away"
        return "draw"

    # BTTS
    if market in ("btts_yes", "btts_no"):
        both = (hs > 0 and aw > 0)
        return "btts_yes" if both else "btts_no"

    # Totals
    total = hs + aw
    if market == "over_2_5": return "over_2_5" if total > 2 else "under_2_5"
    if market == "under_2_5": return "under_2_5" if total <= 2 else "over_2_5"
    if market == "over_1_5": return "over_1_5" if total > 1 else "under_1_5"
    if market == "under_1_5": return "under_1_5" if total <= 1 else "over_1_5"
    if market == "over_3_5": return "over_3_5" if total > 3 else "under_3_5"
    if market == "under_3_5": return "under_3_5" if total <= 3 else "over_3_5"

    return None


# ============================================================
# EQUITY / STREAK METRICS
# ============================================================

def update_equity_metrics(row: Dict[str, Any], pnl: float) -> None:
    row["equity"] += pnl
    if row["equity"] > row["peak_equity"]:
        row["peak_equity"] = row["equity"]

    drawdown_abs = row["peak_equity"] - row["equity"]
    if drawdown_abs > row["max_drawdown_abs"]:
        row["max_drawdown_abs"] = drawdown_abs

    # DD% считаем от пика strategy-equity.
    # Если пик == 0, процентную просадку не считаем.
    if row["peak_equity"] > 0:
        dd_pct = drawdown_abs / row["peak_equity"] * 100.0
        if dd_pct > row["max_drawdown_pct"]:
            row["max_drawdown_pct"] = dd_pct


def update_streaks(row: Dict[str, Any], outcome: str) -> None:
    if outcome == "win":
        row["current_win_streak"] += 1
        row["current_loss_streak"] = 0
        if row["current_win_streak"] > row["max_win_streak"]:
            row["max_win_streak"] = row["current_win_streak"]
    elif outcome == "loss":
        row["current_loss_streak"] += 1
        row["current_win_streak"] = 0
        if row["current_loss_streak"] > row["max_loss_streak"]:
            row["max_loss_streak"] = row["current_loss_streak"]
    else:
        row["current_win_streak"] = 0
        row["current_loss_streak"] = 0


# ============================================================
# STRATEGY STATISTICS
# ============================================================

def init_strategy_row() -> Dict[str, Any]:
    return {
        "seen": 0,
        "bet": 0,
        "small": 0,
        "pass": 0,
        "valid": 0,
        "invalid": 0,
        "validator_rejected": 0,
        "markets": Counter(),

        "stake_sum": 0.0,
        "ev_sum": 0.0,
        "avg_odds_sum": 0.0,

        "scored": 0,
        "won": 0,
        "lost": 0,
        "push": 0,
        "profit": 0.0,

        # equity / drawdown / streaks
        "equity": 0.0,
        "peak_equity": 0.0,
        "max_drawdown_abs": 0.0,
        "max_drawdown_pct": 0.0,

        "current_loss_streak": 0,
        "max_loss_streak": 0,
        "current_win_streak": 0,
        "max_win_streak": 0,
    }


def update_strategy_stats(
    strategy_stats: Dict[str, Dict[str, Any]],
    match: "Match",
    rec: Dict[str, Any],
    valid: bool,
    bankroll: float,
    detect_league_key_fn=None,
) -> None:
    key = get_strategy_bucket(match, rec, detect_league_key_fn)
    row = strategy_stats[key]

    row["seen"] += 1

    decision = rec.get("decision", "PASS")
    if decision == "BET":
        row["bet"] += 1
    elif decision == "SMALL":
        row["small"] += 1
    else:
        row["pass"] += 1

    if valid:
        row["valid"] += 1
    else:
        row["invalid"] += 1

    if rec.get("validator_rejected"):
        row["validator_rejected"] += 1

    market = rec.get("market")
    if market and market != "pass":
        row["markets"][market] += 1

    odds = rec.get("odds")
    if odds is not None:
        try:
            row["avg_odds_sum"] += float(odds)
        except Exception:
            pass

    ev = rec.get("ev")
    if ev is not None:
        try:
            row["ev_sum"] += float(ev)
        except Exception:
            pass

    stake_abs = rec.get("stake")
    if stake_abs is None:
        stake_pct = rec.get("stake_pct")
        try:
            if stake_pct is not None:
                stake_abs = float(stake_pct) * bankroll
        except Exception:
            stake_abs = None

    if stake_abs is None:
        stake_abs = 0.0

    try:
        stake_abs = float(stake_abs)
    except Exception:
        stake_abs = 0.0

    if decision in ("BET", "SMALL") and valid:
        row["stake_sum"] += stake_abs

    actual_market = resolve_actual_market_from_match(match, rec)

    if actual_market and decision in ("BET", "SMALL") and valid and market in (
        "home", "away", "draw", "btts_yes", "btts_no",
        "over_2_5", "under_2_5", "over_1_5", "under_1_5", "over_3_5", "under_3_5"
    ):
        row["scored"] += 1

        try:
            odds_f = float(rec.get("odds") or 0.0)
        except Exception:
            odds_f = 0.0

        if market == actual_market:
            row["won"] += 1
            pnl = stake_abs * (odds_f - 1.0)
            row["profit"] += pnl
            update_equity_metrics(row, pnl)
            update_streaks(row, "win")
        else:
            row["lost"] += 1
            pnl = -stake_abs
            row["profit"] += pnl
            update_equity_metrics(row, pnl)
            update_streaks(row, "loss")
    else:
        update_streaks(row, "push")


# ============================================================
# SUMMARY PRINTING
# ============================================================

def print_strategy_summary(strategy_stats: Dict[str, Dict[str, Any]], backtest: bool = False) -> None:
    print("\n" + "=" * 120)
    print("SUMMARY BY STRATEGY")
    print("=" * 120)

    rows = []
    for key, row in strategy_stats.items():
        placed = row["bet"] + row["small"]
        avg_ev = (row["ev_sum"] / placed) if placed else 0.0
        avg_odds = (row["avg_odds_sum"] / placed) if placed else 0.0
        avg_stake = (row["stake_sum"] / row["scored"]) if row["scored"] else 0.0
        roi = (row["profit"] / row["stake_sum"] * 100.0) if row["stake_sum"] > 0 else 0.0
        hit = (row["won"] / row["scored"] * 100.0) if row["scored"] > 0 else 0.0

        rows.append({
            "key": key,
            "seen": row["seen"],
            "bet": row["bet"],
            "small": row["small"],
            "pass": row["pass"],
            "valid": row["valid"],
            "invalid": row["invalid"],
            "validator_rejected": row["validator_rejected"],
            "avg_ev": avg_ev,
            "avg_odds": avg_odds,
            "avg_stake": avg_stake,
            "stake_sum": row["stake_sum"],
            "scored": row["scored"],
            "won": row["won"],
            "lost": row["lost"],
            "profit": row["profit"],
            "roi": roi,
            "hit": hit,
            "max_dd_abs": row["max_drawdown_abs"],
            "max_dd_pct": row["max_drawdown_pct"],
            "max_ls": row["max_loss_streak"],
            "max_ws": row["max_win_streak"],
        })

    rows.sort(key=lambda x: (x["roi"], x["profit"], x["bet"] + x["small"]), reverse=True)

    for r in rows:
        if backtest:
            print(
                f"{r['key']}\n"
                f"  seen={r['seen']} | BET={r['bet']} | SMALL={r['small']} | PASS={r['pass']} | "
                f"valid={r['valid']} | invalid={r['invalid']} | rejected={r['validator_rejected']}\n"
                f"  scored={r['scored']} | W={r['won']} | L={r['lost']} | hit={r['hit']:.2f}%\n"
                f"  staked={r['stake_sum']:.2f} | profit={r['profit']:+.2f} | ROI={r['roi']:+.2f}% | avg_stake={r['avg_stake']:.2f}\n"
                f"  avg_odds={r['avg_odds']:.3f} | avg_ev={r['avg_ev']:+.4f} | "
                f"maxDD={r['max_dd_abs']:.2f} ({r['max_dd_pct']:.2f}%) | maxLS={r['max_ls']} | maxWS={r['max_ws']}"
            )
        else:
            print(
                f"{r['key']}\n"
                f"  seen={r['seen']} | BET={r['bet']} | SMALL={r['small']} | PASS={r['pass']} | "
                f"valid={r['valid']} | invalid={r['invalid']} | rejected={r['validator_rejected']}\n"
                f"  avg_odds={r['avg_odds']:.3f} | avg_ev={r['avg_ev']:+.4f}"
            )

    print("=" * 120)
