# -*- coding: utf-8 -*-
"""
Hockey-specific strategy module.

Extracted from agent_handoff_v7.py to keep hockey decision logic in one place.

Strategy paths by league:
  KHL     — intersection of underdog_live + defensive_wall (edge >= 0.5%, odds 1.70-3.80, history >= 3)
  NHL     — nhl_draw_tight single-strategy path (draw tight score)
  CZECH   — czech_home_favorite single-strategy path
  NLA     — nla_bern_away_draw (away draw when Bern plays)

Imports strategy primitives (implied_probs, Pick, underdog_live, etc.) from
hockey_backtest_fast_v2.py — those remain the canonical implementation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from hockey_backtest_fast_v2 import (
    implied_probs, odds_for_market, history_games,
    underdog_live, defensive_wall, nhl_draw_tight,
    czech_home_favorite, del_home_form5, czech_home_sd,
    shl_skelleftea_home, Pick,
)


# ============================================================
# LEAGUE CONFIG
# ============================================================

HOCKEY_LEAGUE_CONFIG: Dict[str, Dict[str, Any]] = {
    "KHL": {
        "mode": "intersection",
        "strategies": ["underdog_live", "defensive_wall"],
        "stake_mode": "bankroll_regime_v1",
    },
    "CZECH": {
        "mode": "multi_single",
        "strategies": ["czech_home_favorite", "czech_home_sd"],
        "stake_mode": "flat_pct_1_00",
    },
    # "NHL": {  # Отключено — стратегия убыточна на реальных данных (ROI -7%)
    #     "mode": "single",
    #     "strategies": ["nhl_draw_tight"],
    #     "stake_mode": "flat_pct_1_00",
    # },
    "NLA": {
        "mode": "single",
        "strategies": ["nla_bern_away_draw"],
        "stake_mode": "flat_pct_1_00",
    },
    "DEL": {
        "mode": "single",
        "strategies": ["del_home_form5"],
        "stake_mode": "flat_pct_1_00",
    },
    "SHL": {
        "mode": "single",
        "strategies": ["shl_skelleftea_home"],
        "stake_mode": "flat_pct_1_00",
    },
}


# ============================================================
# LEAGUE DETECTION
# ============================================================

def detect_league_key(league: str) -> Optional[str]:
    """
    Detect the hockey league key for strategy routing.

    Args:
        league: League name string.

    Returns:
        One of "KHL", "CZECH", "NHL", "NLA", "DEL", "SHL", or None.
    """
    if not league:
        return None
    l = league.lower()

    if any(t in l for t in ["\u043a\u0445\u043b", "khl", "\u0444\u043e\u043d\u0431\u0435\u0442 \u043a\u0445\u043b", "thesports khl"]):
        return "KHL"
    if any(t in l for t in ["\u0447\u0435\u0445", "czech", "extraliga"]):
        return "CZECH"
    if any(t in l for t in ["\u043d\u0445\u043b", "nhl"]):
        return "NHL"
    if any(t in l for t in ["\u0448\u0432\u0435\u0439\u0446\u0430\u0440", "national league", "\u043d\u0430\u0446\u0438\u043e\u043d\u0430\u043b\u044c\u043d\u0430\u044f \u043b\u0438\u0433\u0430"]):
        return "NLA"
    if any(t in l for t in ["\u0433\u0435\u0440\u043c\u0430\u043d", "del."]) and "del2" not in l:
        return "DEL"
    if any(t in l for t in ["\u0448\u0432\u0435\u0446", "shl."]) and "allsvenskan" not in l:
        return "SHL"
    return None


# ============================================================
# FEATURES
# ============================================================

HOCKEY_FEATURE_MAP_BACKTEST: Dict[str, Any] = {
    # Maps backtest_hockey_features columns -> hockey_match_features names
    "expected_goal_diff_proxy": None,  # computed
    "home_goal_diff_vol5": None,
    "away_goal_diff_vol5": None,
    "home_total_goals_vol5": None,
    "away_total_goals_vol5": None,
    "home_gf_avg5": None,
    "away_gf_avg5": None,
    "home_ga_avg5": None,
    "away_ga_avg5": None,
    "home_ga_avg10": None,
    "away_ga_avg10": None,
    "expected_total_goals_proxy": None,
    "expected_match_tightness": None,
    "expected_defense_balance": None,
}
HOCKEY_FEATURE_MAP_BACKTEST[  # noqa: E731 – populated at import time
    "expected_goal_diff_proxy"
] = lambda d: (d.get("home_ppg_before", 0) or 0) - (d.get("away_ppg_before", 0) or 0)


def _backtest_to_features(d: Dict[str, Any]) -> Dict[str, Any]:
    """Map backtest_hockey_features row to hockey_match_features schema."""
    gp_h = max(d.get("home_gp_before", 1) or 1, 1)
    gp_a = max(d.get("away_gp_before", 1) or 1, 1)
    home_gf = d.get("home_gf_before", 0) or 0
    home_ga = d.get("home_ga_before", 0) or 0
    away_gf = d.get("away_gf_before", 0) or 0
    away_ga = d.get("away_ga_before", 0) or 0
    home_ppg = d.get("home_ppg_before", 0) or 0
    away_ppg = d.get("away_ppg_before", 0) or 0

    return {
        "match_id": d.get("match_id"),
        "strength_diff_ppg": d.get("strength_diff_ppg"),
        "strength_diff_form5": d.get("strength_diff_form5"),
        "strength_diff_form10": d.get("strength_diff_form10"),
        "expected_goal_diff_proxy": home_ppg - away_ppg,
        "home_goal_diff_vol5": abs(d.get("form5_home_gd", 0) or 0) / 5.0,
        "away_goal_diff_vol5": abs(d.get("form5_away_gd", 0) or 0) / 5.0,
        "home_total_goals_vol5": (home_gf + home_ga) / gp_h,
        "away_total_goals_vol5": (away_gf + away_ga) / gp_a,
        "home_ppg_all_before": d.get("home_ppg_before"),
        "away_ppg_all_before": d.get("away_ppg_before"),
        "home_gf_avg5": home_gf / gp_h,
        "away_gf_avg5": away_gf / gp_a,
        "home_ga_avg5": home_ga / gp_h,
        "away_ga_avg5": away_ga / gp_a,
        "home_ga_avg10": home_ga / gp_h,
        "away_ga_avg10": away_ga / gp_a,
        "expected_total_goals_proxy": (home_gf + away_gf) / gp_h,
        "expected_match_tightness": 1.0 - abs(home_ppg - away_ppg) / 3.0,
        "expected_defense_balance": 1.0 - abs(home_ga - away_ga) / max(home_ga, 1),
        "home_games_before": d.get("home_gp_before"),
        "away_games_before": d.get("away_gp_before"),
        "home_drawrate_before": d.get("home_drawrate_before"),
        "away_drawrate_before": d.get("away_drawrate_before"),
        "home_winrate_before": d.get("home_winrate_before"),
        "away_winrate_before": d.get("away_winrate_before"),
        "home_ppg_before": d.get("home_ppg_before"),
        "away_ppg_before": d.get("away_ppg_before"),
    }


def get_hockey_features(conn, match_id: int) -> Optional[Dict[str, Any]]:
    """
    Get hockey features for a match from hockey_match_features table.
    Falls back to backtest_hockey_features for backtest mode.
    """
    row = conn.execute(
        "SELECT * FROM hockey_match_features WHERE match_id = ?",
        (match_id,),
    ).fetchone()
    if row:
        return dict(row)
    try:
        row = conn.execute(
            "SELECT * FROM backtest_hockey_features WHERE match_id = ?",
            (match_id,),
        ).fetchone()
        if row:
            return _backtest_to_features(dict(row))
    except Exception:
        pass
    return None


# ============================================================
# VALIDATION
# ============================================================

def validate_hockey_recommendation(rec: Dict[str, Any], match) -> Tuple[bool, List[str]]:
    """
    Hockey-specific lightweight validation.
    Only checks essential requirements without applying football-style restrictions.
    """
    notes: List[str] = []

    if rec.get("market") == "pass" or rec.get("decision") == "PASS":
        notes.append("Hockey recommendation marked as PASS")
        return False, notes

    if not rec.get("market"):
        notes.append("No market specified")
        return False, notes

    if not rec.get("odds"):
        notes.append("No odds specified")
        return False, notes

    ev = float(rec.get("ev", 0))
    if ev <= 0:
        notes.append(f"Negative or zero EV: {ev}")
        return False, notes

    if not rec.get("confirmed_facts"):
        notes.append("No confirmed facts")
        return False, notes

    if not getattr(match, "id", None):
        notes.append("No valid match_id")
        return False, notes

    odds = float(rec.get("odds", 0))
    if odds < 1.50:
        notes.append(f"Odds too low: {odds} < 1.50")
        return False, notes

    if odds > 6.0:
        notes.append(f"Odds too high: {odds} > 6.0")
        return False, notes

    notes.append("VALID")
    return True, notes


# ============================================================
# PROCESS HOCKEY MATCH
# ============================================================

# Module-level reference used inside process_hockey_match.
# Set by agent_handoff_v7 at import time to avoid circular dependency.
_compute_kelly_ref: Optional[Any] = None
_resolve_stake_ref: Optional[Any] = None
_GLOBAL_ARGS_ref: Optional[Any] = None


def _set_dependencies(compute_kelly_fn, resolve_stake_fn, global_args_fn) -> None:
    """Wire in functions from agent_handoff_v7 to avoid circular imports."""
    global _compute_kelly_ref, _resolve_stake_ref, _GLOBAL_ARGS_ref
    _compute_kelly_ref = compute_kelly_fn
    _resolve_stake_ref = resolve_stake_fn
    _GLOBAL_ARGS_ref = global_args_fn


class _Match:
    """Minimal Match dataclass for type hints."""
    id: int = 0
    sport: str = ""
    league: str = ""
    home_team: str = ""
    away_team: str = ""
    odds_home: float = 0.0
    odds_draw: float = 0.0
    odds_away: float = 0.0
    match_date: str = ""


def _dry_print_fail(debug_info: Dict[str, Any], match) -> None:
    """Print debug info for a failed match."""
    ga = _GLOBAL_ARGS_ref
    dry = getattr(ga, "dry_run", False) if ga else False
    if not dry:
        return
    print(f"\n[HOCKEY DEBUG] Match ID: {match.id} | {match.home_team} — {match.away_team}")
    print(f"  League: {match.league}")
    print(f"  FAIL: {debug_info.get('failed_reason', 'unknown reason')}")
    if 'underdog_live' in debug_info:
        print(f"  Underdog Live: {debug_info.get('underdog_live')}")
    if 'defensive_wall' in debug_info:
        print(f"  Defensive Wall: {debug_info.get('defensive_wall')}")
    if 'fp_or_fb' in debug_info:
        print(f"  FP_OR_FB: {debug_info.get('fp_or_fb')}")


def process_hockey_match(conn, match, bankroll: float) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Process a hockey match using the strategies from hockey_backtest_fast_v2.py.

    Returns:
        Tuple of (recommendation dict or None, debug_info dict).
        This is the dedicated hockey decision path that bypasses LLM
        and uses rule-driven logic.
    """
    debug_info: Dict[str, Any] = {
        "match_id": match.id,
        "home_team": match.home_team,
        "away_team": match.away_team,
        "odds_home": match.odds_home,
        "odds_draw": match.odds_draw,
        "odds_away": match.odds_away,
        "is_khl_regular": False,
        "features_found": False,
        "pick1_exists": False,
        "pick2_exists": False,
        "pick1_market": None,
        "pick2_market": None,
        "pick1_edge": None,
        "pick2_edge": None,
        "markets_match": False,
        "both_edges_positive": False,
        "is_underdog": False,
        "odds_in_range": False,
        "min_history_ok": False,
        "failed_reason": None,
        "final_recommendation": False,
    }

    if match.sport != "hockey":
        debug_info["failed_reason"] = "Not a hockey match"
        _dry_print_fail(debug_info, match)
        return None, debug_info

    league_key = detect_league_key(match.league)
    league_config = HOCKEY_LEAGUE_CONFIG.get(league_key, {})
    debug_info["league_key"] = league_key
    debug_info["league_mode"] = league_config.get("mode") if league_config else None
    debug_info["is_khl_regular"] = ("\u041a\u0425\u041b" in match.league and "\u0420\u0435\u0433\u0443\u043b\u044f\u0440\u043d\u044b\u0439" in match.league)

    if not league_key:
        debug_info["failed_reason"] = "Unknown hockey league"
        _dry_print_fail(debug_info, match)
        return None, debug_info

    if not league_config or league_config.get("mode") == "disabled":
        debug_info["failed_reason"] = f"League disabled: {league_key}"
        _dry_print_fail(debug_info, match)
        return None, debug_info

    features = get_hockey_features(conn, match.id)
    debug_info["features_found"] = bool(features)

    strategies = league_config.get("strategies", [])
    features_required = not any(
        s in strategies for s in ["nhl_draw_tight", "nla_bern_away_draw"]
    )
    # DEL, SHL, and multi_single CZECH need features for form5/strength_diff
    if league_key in ("DEL", "SHL") or league_config.get("mode") == "multi_single":
        features_required = True
    if not features and features_required:
        debug_info["failed_reason"] = "No hockey features found"
        _dry_print_fail(debug_info, match)
        return None, debug_info

    row: Dict[str, Any] = {
        "odds_home": match.odds_home,
        "odds_draw": match.odds_draw,
        "odds_away": match.odds_away,
        "home_team": match.home_team,
        "away_team": match.away_team,
        "match_date": match.match_date,
        "league": match.league,
    }
    if features:
        for k, v in features.items():
            if k not in ("id", "match_id", "updated_at"):
                row[k] = v

    # --- League-specific strategy dispatch ---
    # DEL: del_home_form5
    if "del_home_form5" in strategies:
        pick1 = del_home_form5(row)
        pick2 = pick1

    # CZECH: multi_single mode — try each strategy, return first positive EV
    elif league_config.get("mode") == "multi_single":
        pick1 = None
        for strat_name in strategies:
            fn = {
                "czech_home_favorite": czech_home_favorite,
                "czech_home_sd": czech_home_sd,
            }.get(strat_name)
            if fn:
                p = fn(row)
                if p and p.ev > 0:
                    pick1 = p
                    debug_info["active_strategy"] = strat_name
                    break
        pick2 = pick1

    # SHL: shl_skelleftea_home
    elif "shl_skelleftea_home" in strategies:
        pick1 = shl_skelleftea_home(row)
        pick2 = pick1

    elif "nhl_draw_tight" in strategies:
        pick1 = nhl_draw_tight(row)
        pick2 = pick1
    elif "czech_home_favorite" in strategies:
        pick1 = czech_home_favorite(row)
        pick2 = pick1
    elif "nla_bern_away_draw" in strategies:
        away = str(getattr(match, "away_team", "")).lower()
        od = match.odds_draw or 0
        if "\u0431\u0435\u0440\u043d" in away and 4.0 <= od <= 5.2:
            implied = 1.0 / od if od > 0 else 0
            model_prob = min(0.342 * 1.05, 0.95)
            ev = model_prob * od - 1.0
            stake = round(bankroll * 0.01)
            debug_info["markets_match"] = True
            debug_info["both_edges_positive"] = True
            debug_info["final_recommendation"] = True
            return {
                "market": "draw",
                "market_label": "X",
                "odds": od,
                "our_probability": model_prob,
                "market_probability": implied,
                "ev": ev,
                "kelly": 0.01,
                "kelly_quarter": 0.0025,
                "stake_pct": 0.01,
                "stake": stake,
                "confirmed_facts": [f"\u0411\u0435\u0440\u043d \u0432 \u0433\u043e\u0441\u0442\u044f\u0445 | draw_rate=34.2% | odds={od:.2f}"],
                "market_error": f"NLA strategy nla_bern_away_draw: draw",
                "rule": "NLA_BERN_AWAY_DRAW",
                "live_rule_family": "nla_bern_away_draw",
                "strategy_name": "nla_bern_away_draw",
                "recommended_action": "BET",
                "signal_type": "RULE_DRIVEN",
                "decision": "BET",
            }, debug_info
        else:
            pick1 = None
            pick2 = None
    else:
        # KHL intersection path
        pick1 = underdog_live(row)
        pick2 = defensive_wall(row)

    # Strategy results in debug
    debug_info["pick1_exists"] = bool(pick1)
    debug_info["pick2_exists"] = bool(pick2)

    if pick1:
        debug_info["pick1_market"] = pick1.market
        debug_info["pick1_edge"] = round(pick1.edge, 4)
        debug_info["underdog_live"] = {
            "market": pick1.market,
            "model_prob": round(pick1.model_prob, 4),
            "edge": round(pick1.edge, 4),
            "ev": round(pick1.ev, 4),
        }

    if pick2:
        debug_info["pick2_market"] = pick2.market
        debug_info["pick2_edge"] = round(pick2.edge, 4)
        debug_info["defensive_wall"] = {
            "market": pick2.market,
            "model_prob": round(pick2.model_prob, 4),
            "edge": round(pick2.edge, 4),
            "score": round(pick2.score, 4),
        }

    # Check both strategies agree on market
    if not pick1 or not pick2 or pick1.market != pick2.market:
        debug_info["markets_match"] = False
        debug_info["failed_reason"] = "Markets don't match or strategy returned None"
        ga = _GLOBAL_ARGS_ref
        if getattr(ga, "dry_run", False):
            print(f"\n[HOCKEY DEBUG] Match ID: {match.id} | {match.home_team} — {match.away_team}")
            print(f"  Odds: H={match.odds_home:.2f} D={match.odds_draw:.2f} A={match.odds_away:.2f}")
            print(f"  Underdog Live: {debug_info.get('underdog_live')}")
            print(f"  Defensive Wall: {debug_info.get('defensive_wall')}")
            print(f"  FAIL: {debug_info['failed_reason']}")
        _dry_print_fail(debug_info, match)
        return None, debug_info

    debug_info["markets_match"] = True

    # True intersection check (edge >= 0.5%)
    if pick1.edge < 0.005 or pick2.edge < 0.005:
        debug_info["both_edges_positive"] = False
        debug_info["failed_reason"] = (
            f"Edge too small: underdog_live={pick1.edge:.4f}, "
            f"defensive_wall={pick2.edge:.4f}"
        )
        ga = _GLOBAL_ARGS_ref
        if getattr(ga, "dry_run", False):
            print(f"\n[HOCKEY DEBUG] Match ID: {match.id} | {match.home_team} — {match.away_team}")
            print(f"  Odds: H={match.odds_home:.2f} D={match.odds_draw:.2f} A={match.odds_away:.2f}")
            print(f"  Underdog Live: {debug_info.get('underdog_live')}")
            print(f"  Defensive Wall: {debug_info.get('defensive_wall')}")
            print(f"  FAIL: {debug_info['failed_reason']}")
        _dry_print_fail(debug_info, match)
        return None, debug_info

    debug_info["both_edges_positive"] = True

    # NHL/CZECH/DEL/SHL single-strategy path — skip KHL intersection checks
    if league_key in ("NHL", "CZECH", "DEL", "SHL") or league_config.get("mode") == "multi_single":
        if not pick1:
            debug_info["failed_reason"] = f"{league_config['strategies']} returned None"
            return None, debug_info
        odds = odds_for_market(row, pick1.market)
        if not odds:
            debug_info["failed_reason"] = "No odds for market"
            return None, debug_info
        market_map = {"H": "home", "A": "away", "D": "draw"}
        market = market_map[pick1.market]
        ev_val = pick1.model_prob * odds - 1.0
        compute_kelly = _compute_kelly_ref
        resolve_stake = _resolve_stake_ref
        kelly = compute_kelly(pick1.model_prob, odds)
        kelly_quarter = max(0.0, kelly * 0.25)
        override_stake_pct, _, _ = resolve_stake(conn, bankroll, match, {})
        stake_pct = override_stake_pct if override_stake_pct is not None else min(kelly_quarter, 0.05)
        debug_info["final_recommendation"] = True
        strat_name = debug_info.get("active_strategy", league_config["strategies"][0])
        return {
            "market": market,
            "market_label": {"home": "\u041f1", "draw": "X", "away": "\u041f2"}[market],
            "odds": odds,
            "our_probability": pick1.model_prob,
            "market_probability": 1.0 / odds,
            "ev": ev_val,
            "kelly": kelly,
            "kelly_quarter": kelly_quarter,
            "stake_pct": stake_pct,
            "market_error": f"{strat_name}: {pick1.market}",
            "confirmed_facts": [
                f"Strategy signal: {strat_name}",
                f"Edge: {pick1.edge:.4f}",
            ],
            "unconfirmed": [],
            "decision": "BET",
            "signal_type": "High" if pick1.ev > 0.15 else "Medium",
            "strategy_name": strat_name,
            "strategy_family": strat_name,
            "live_rule_family": strat_name,
            "rule_driven": True,
        }, debug_info

    # KHL intersection continuation
    imp = implied_probs(row)
    if not imp:
        debug_info["failed_reason"] = "Could not calculate implied probabilities"
        _dry_print_fail(debug_info, match)
        return None, debug_info

    fav = "H" if imp["H"] > imp["A"] else "A"
    is_underdog = pick1.market != fav
    debug_info["is_underdog"] = is_underdog
    debug_info["favorite"] = fav

    if not is_underdog:
        debug_info["failed_reason"] = f"Not an underdog (favorite is {fav})"
        ga = _GLOBAL_ARGS_ref
        if getattr(ga, "dry_run", False):
            print(f"\n[HOCKEY DEBUG] Match ID: {match.id} | {match.home_team} — {match.away_team}")
            print(f"  Odds: H={match.odds_home:.2f} D={match.odds_draw:.2f} A={match.odds_away:.2f}")
            print(f"  Underdog Live: {debug_info.get('underdog_live')}")
            print(f"  Defensive Wall: {debug_info.get('defensive_wall')}")
            print(f"  FAIL: {debug_info['failed_reason']}")
        _dry_print_fail(debug_info, match)
        return None, debug_info

    odds = odds_for_market(row, pick1.market)
    odds_in_range = odds and 1.70 <= odds <= 3.80
    debug_info["odds_in_range"] = odds_in_range
    debug_info["odds"] = odds

    if not odds_in_range:
        debug_info["failed_reason"] = f"Odds out of range: {odds:.2f} (must be 1.70-3.80)"
        ga = _GLOBAL_ARGS_ref
        if getattr(ga, "dry_run", False):
            print(f"\n[HOCKEY DEBUG] Match ID: {match.id} | {match.home_team} — {match.away_team}")
            print(f"  Odds: H={match.odds_home:.2f} D={match.odds_draw:.2f} A={match.odds_away:.2f}")
            print(f"  Underdog Live: {debug_info.get('underdog_live')}")
            print(f"  Defensive Wall: {debug_info.get('defensive_wall')}")
            print(f"  FAIL: {debug_info['failed_reason']}")
        _dry_print_fail(debug_info, match)
        return None, debug_info

    history_count = history_games(row)
    min_history_ok = history_count >= 3
    debug_info["min_history_ok"] = min_history_ok
    debug_info["history_count"] = history_count

    if not min_history_ok:
        debug_info["failed_reason"] = f"Not enough history: {history_count} < 3"
        ga = _GLOBAL_ARGS_ref
        if getattr(ga, "dry_run", False):
            print(f"\n[HOCKEY DEBUG] Match ID: {match.id} | {match.home_team} — {match.away_team}")
            print(f"  Odds: H={match.odds_home:.2f} D={match.odds_draw:.2f} A={match.odds_away:.2f}")
            print(f"  Underdog Live: {debug_info.get('underdog_live')}")
            print(f"  Defensive Wall: {debug_info.get('defensive_wall')}")
            print(f"  FAIL: {debug_info['failed_reason']}")
        _dry_print_fail(debug_info, match)
        return None, debug_info

    # Build recommendation
    market_map = {"H": "home", "A": "away", "D": "draw"}
    market = market_map[pick1.market]
    market_probability = 1.0 / odds
    ev_val = pick1.model_prob * odds - 1.0
    compute_kelly = _compute_kelly_ref
    resolve_stake = _resolve_stake_ref
    kelly = compute_kelly(pick1.model_prob, odds)
    kelly_quarter = max(0.0, kelly * 0.25)
    stake_pct = min(kelly_quarter, 0.05)
    stake_mode_meta: Dict[str, Any] = {}

    override_stake_pct, override_stake_abs, stake_meta = resolve_stake(conn, bankroll, match, {})
    if override_stake_pct is not None:
        stake_pct = override_stake_pct
        stake_mode_meta = stake_meta

    debug_info["final_recommendation"] = True

    ga = _GLOBAL_ARGS_ref
    if getattr(ga, "dry_run", False):
        print(f"\n[HOCKEY DEBUG] Match ID: {match.id} | {match.home_team} — {match.away_team}")
        print(f"  Odds: H={match.odds_home:.2f} D={match.odds_draw:.2f} A={match.odds_away:.2f}")
        print(f"  Underdog Live: {debug_info.get('underdog_live')}")
        print(f"  Defensive Wall: {debug_info.get('defensive_wall')}")
        print(f"  Markets match: {debug_info['markets_match']}")
        print(f"  Is underdog: {debug_info['is_underdog']} (favorite is {fav})")
        print(f"  Odds in range: {debug_info['odds_in_range']} ({odds:.2f})")
        print(f"  Min history OK: {debug_info['min_history_ok']} ({history_count} games)")
        print(f"  PASS: All filters passed, creating recommendation for {market} @ {odds:.2f}")
        if stake_mode_meta:
            print(f"  Stake mode: {stake_mode_meta.get('stake_mode_name')} ({stake_mode_meta.get('stake_mode_type')})")
            print(f"  Stake reason: {stake_mode_meta.get('stake_mode_reason')}")

    strategy_name = "intersection"
    strategy_family = "hockey_underdog_defensive"
    if league_key == "NHL":
        strategy_name = "nhl_draw_tight"
        strategy_family = "nhl_draw_tight"
    elif league_key == "CZECH":
        strategy_name = "czech_home_favorite"
        strategy_family = "czech_home_favorite"
    elif league_key == "NLA":
        strategy_name = "nla_bern_away_draw"
        strategy_family = "nla_bern_away_draw"

    recommendation: Dict[str, Any] = {
        "market": market,
        "market_label": {"home": "\u041f1", "draw": "X", "away": "\u041f2"}[market],
        "odds": odds,
        "our_probability": pick1.model_prob,
        "market_probability": market_probability,
        "ev": ev_val,
        "kelly": kelly,
        "kelly_quarter": kelly_quarter,
        "stake_pct": stake_pct,
        "market_error": f"Hockey strategy {strategy_name}: {pick1.market}",
        "confirmed_facts": [
            f"Underdog edge: {pick1.edge:.4f}",
            f"Defensive wall score: {pick2.score:.2f}",
            f"Expected goal diff: {row.get('expected_goal_diff_proxy', 0):.2f}",
        ],
        "unconfirmed": [],
        "lineup_data_available": False,
        "signal_type": "Medium",
        "confidence": 6,
        "decision": "BET",
        "recommended_action": "BET",
        "rule_driven": True,
        "live_rule_family": strategy_family,
        "strategy_name": strategy_name,
        "shadow_only": False,
        "hockey_path": True,
    }

    if stake_mode_meta:
        recommendation.update({
            "stake_mode_name": stake_mode_meta.get("stake_mode_name"),
            "stake_mode_type": stake_mode_meta.get("stake_mode_type"),
            "stake_mode_reason": stake_mode_meta.get("stake_mode_reason"),
        })
        if "base_bankroll" in stake_mode_meta:
            recommendation.update({
                "base_bankroll": stake_mode_meta.get("base_bankroll"),
                "current_bankroll": stake_mode_meta.get("current_bankroll"),
                "bankroll_regime": stake_mode_meta.get("bankroll_regime"),
            })

    return recommendation, debug_info
