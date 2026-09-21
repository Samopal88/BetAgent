#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — analysis_helpers/match_utils.py

Pure helper functions for:
- BA rule → market mapping
- Display tag formatting (_ba_tag, _rule_tag)
- Market family classification
- Placeholder match detection
- Safe probability conversion
- Float coercion

No DB, no orchestration, no LLM calls, no global state.
Extracted from agent_handoff_v7.py Step 5 (2026-04-14).
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def ba_rule_to_market(rule: Optional[str]) -> Optional[str]:
    """Map BA rule to specific market."""
    if not rule:
        return None
    mapping = {
        "DRAW_SA": "draw",
        "SA_AWAY_DRAW": "draw",
        "DRAW_BL1_FL1": "draw",
        "AWAY_SA": "away",
        "AWAY_BL1": "away",
        "P1_PD": "home",
    }
    return mapping.get(rule)


def _ba_tag(match: "Match") -> str:
    """Display tag for backtest-approved matches."""
    if getattr(match, "is_backtest_approved", False):
        rule = getattr(match, "ba_rule", None) or "BA"
        source = getattr(match, "shortlist_source", "ba")
        pure_ba = getattr(match, "pure_ba_mode", False)
        pure_tag = " | PURE_BA" if pure_ba else ""
        return f" | BA:{rule} | SRC:{source}{pure_tag}"
    return ""


def _rule_tag(rec: Dict[str, Any]) -> str:
    """Display tag for rule-driven recommendations."""
    if rec.get("rule_driven", False):
        rule = rec.get("live_rule_family", "UNKNOWN")
        return f" | [LIVE_RULE:{rule}]"
    if rec.get("hockey_path", False):
        return " | [HOCKEY]"
    if rec.get("shadow_only", False):
        return " | [SHADOW]"
    return ""


def get_market_family(market: str) -> str:
    """Classify market into a family to prevent duplicate analysis."""
    if market in ("home", "draw", "away"):
        return "1X2"
    if "total" in market.lower() or market.startswith("over_") or market.startswith("under_"):
        return "TOTALS"
    if "handicap" in market.lower():
        return "HANDICAP"
    if market in ("btts_yes", "btts_no", "BTTS_YES", "BTTS_NO"):
        return "BTTS"
    return market.upper()


def is_placeholder_match(home: str, away: str) -> bool:
    """Check if match has placeholder team names instead of real teams."""
    if not home or not away:
        return True
    bad = {"Хозяева", "Гости", "Hosts", "Guests"}
    return home.strip() in bad or away.strip() in bad


def safe_prob(odds: Optional[float]) -> Optional[float]:
    """Convert odds to implied probability, safely."""
    if odds is None or odds <= 0:
        return None
    return round(1.0 / odds, 4)


def _coerce_float(val: Any) -> Optional[float]:
    """Safely coerce a value to float, returning None on failure."""
    try:
        return None if val is None else float(val)
    except Exception:
        return None
