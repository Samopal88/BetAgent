#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — analysis_helpers/probability_pipeline.py

Pure helper functions for:
- Sport profile loading
- Probability calibration
- Pre-flight checks
- Backtest approval
- Facts normalization

No DB, no orchestration, no LLM calls.
Extracted from agent_handoff_v7.py Step 2 (2026-04-14).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# ============================================================
# SPORT PROFILES
# ============================================================

SPORT_PROFILES_PATH = Path(__file__).resolve().parent.parent / "sport_profiles.json"

try:
    with open(SPORT_PROFILES_PATH, "r", encoding="utf-8") as f:
        SPORT_PROFILES = json.load(f)
except Exception:
    SPORT_PROFILES = {}

DEFAULT_PROFILE = {
    "no_lineup_cap": 0.55,
    "weak_no_lineup_cap": 0.53,
    "lineup_cap": 0.70,
    "no_h2h_penalty": 0.02,
    "short_form_penalty_3": 0.02,
    "short_form_penalty_5": 0.01,
    "medium_no_lineup_penalty": 0.01,
    "weak_no_lineup_penalty": 0.02,
    "lineups_missing_penalty": 0.01,
    "injuries_missing_penalty": 0.02,
    "allow_medium_without_lineups": False,
    "allow_strong_without_lineups": False,
    "min_edge_vs_market": 0.025,
    "min_edge_vs_market_btts": 0.015,
    "min_ev": 0.03,
    "probability_floor": 0.36,
    "preflight_rules": {
        "require_any_data": True,
        "min_form_for_llm": 3,
        "block_if_no_h2h_and_short_form_and_no_lineups": True,
        "min_form_threshold_for_block": 3,
        "require_injuries_for_medium_without_lineups": False,
    },
}


def get_profile(sport: str) -> Dict:
    return SPORT_PROFILES.get(sport, DEFAULT_PROFILE)


# ============================================================
# FORM HELPERS
# ============================================================

def _wins(form: List[Any]) -> int:
    return sum(1 for x in (form or []) if str(x).upper() == "W")


def _draws(form: List[Any]) -> int:
    return sum(1 for x in (form or []) if str(x).upper() == "D")


def _norm_form_list(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        return [str(x).upper() for x in val if str(x).strip()]
    if isinstance(val, str):
        raw = val.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x).upper() for x in parsed if str(x).strip()]
        except Exception:
            pass
        if "," in raw:
            return [x.strip().upper() for x in raw.split(",") if x.strip()]
        return [ch.upper() for ch in raw if ch.upper() in {"W", "D", "L"}]
    return []


def _pick_first_nonempty(src: Dict[str, Any], keys: List[str], default=None):
    for k in keys:
        if k in src:
            v = src.get(k)
            if v not in (None, "", [], {}, ()):
                return v
    return default


# ============================================================
# FACTS NORMALIZATION
# ============================================================

def normalize_known_facts_for_rules(facts: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    src = dict(facts or {})
    out = dict(src)

    out["form_last_5_home"] = _norm_form_list(_pick_first_nonempty(src, [
        "form_last_5_home", "home_form", "form_home", "home_last_5_form",
        "home_form_last_5", "last5_home_form",
    ], []))
    out["form_last_5_away"] = _norm_form_list(_pick_first_nonempty(src, [
        "form_last_5_away", "away_form", "form_away", "away_last_5_form",
        "away_form_last_5", "last5_away_form",
    ], []))

    scalar_aliases = {
        "home_position": ["home_position", "position_home", "table_position_home", "home_rank"],
        "away_position": ["away_position", "position_away", "table_position_away", "away_rank"],
        "home_points": ["home_points", "points_home", "table_points_home"],
        "away_points": ["away_points", "points_away", "table_points_away"],
        "home_goals_scored_avg": ["home_goals_scored_avg", "home_scored_avg", "avg_home_goals_for", "home_goals_for_avg"],
        "away_goals_scored_avg": ["away_goals_scored_avg", "away_scored_avg", "avg_away_goals_for", "away_goals_for_avg"],
        "home_goals_allowed_avg": ["home_goals_allowed_avg", "home_allowed_avg", "avg_home_goals_against", "home_goals_against_avg"],
        "away_goals_allowed_avg": ["away_goals_allowed_avg", "away_allowed_avg", "avg_away_goals_against", "away_goals_against_avg"],
        "h2h_summary": ["h2h_summary", "h2h", "head_to_head_summary"],
        "home_motivation": ["home_motivation"],
        "away_motivation": ["away_motivation"],
        "notes": ["notes", "injury_notes", "match_notes"],
    }
    for dst, aliases in scalar_aliases.items():
        v = _pick_first_nonempty(src, aliases, out.get(dst))
        if v is not None:
            out[dst] = v

    lineup_v = _pick_first_nonempty(src, ["lineup_data_available", "has_lineups"], out.get("lineup_data_available", False))
    out["lineup_data_available"] = bool(lineup_v)

    injuries_v = _pick_first_nonempty(src, ["injury_data_available", "has_injuries"], out.get("injury_data_available", False))
    if not injuries_v:
        notes = str(out.get("notes") or "")
        injuries_v = ("Травмы" in notes or "Injury" in notes or "injury" in notes)
    out["injury_data_available"] = bool(injuries_v)
    return out


def merge_known_facts(primary: Optional[Dict[str, Any]], secondary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    p = normalize_known_facts_for_rules(primary)
    s = normalize_known_facts_for_rules(secondary)
    merged = dict(s)
    merged.update(p)

    for key in ["form_last_5_home", "form_last_5_away"]:
        if not merged.get(key):
            merged[key] = s.get(key) or p.get(key) or []

    for key in [
        "home_position", "away_position", "home_points", "away_points",
        "home_goals_scored_avg", "away_goals_scored_avg",
        "home_goals_allowed_avg", "away_goals_allowed_avg",
        "h2h_summary", "home_motivation", "away_motivation", "notes",
    ]:
        if merged.get(key) in (None, "", [], {}):
            merged[key] = p.get(key) if p.get(key) not in (None, "", [], {}) else s.get(key)

    merged["lineup_data_available"] = bool(p.get("lineup_data_available") or s.get("lineup_data_available"))
    merged["injury_data_available"] = bool(p.get("injury_data_available") or s.get("injury_data_available"))
    return merged


# ============================================================
# BACKTEST APPROVAL
# ============================================================

def is_backtest_approved(match: "Match", facts: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Backtest-approved shortlist rules.
    Conservative rules only: they should bypass pre-flight, not auto-create bets.
    """
    if (match.sport or "").lower() != "football":
        return False, None

    league = (match.league or "").lower()
    home_pos = facts.get("home_position")
    away_pos = facts.get("away_position")
    home_scored = facts.get("home_goals_scored_avg")
    away_scored = facts.get("away_goals_scored_avg")
    home_allowed = facts.get("home_goals_allowed_avg")
    away_allowed = facts.get("away_goals_allowed_avg")
    home_form = facts.get("form_last_5_home") or []
    away_form = facts.get("form_last_5_away") or []
    home_w = _wins(home_form)
    away_w = _wins(away_form)
    home_d = _draws(home_form)
    away_d = _draws(away_form)

    def close_table(max_diff: int = 5) -> bool:
        return home_pos is not None and away_pos is not None and abs(int(home_pos) - int(away_pos)) <= max_diff

    def away_stronger(min_pos_gap: int = 3) -> bool:
        return home_pos is not None and away_pos is not None and int(away_pos) + min_pos_gap <= int(home_pos)

    def home_stronger(min_pos_gap: int = 3) -> bool:
        return home_pos is not None and away_pos is not None and int(home_pos) + min_pos_gap <= int(away_pos)

    # DRAW_SA — Serie A draw shortlist
    if (("серия а" in league or "serie a" in league or league == "sa")
            and match.odds_draw is not None):
        if 3.00 <= float(match.odds_draw) <= 3.85:
            if close_table(5) and abs(home_w - away_w) <= 1:
                if (home_scored is not None and away_scored is not None and
                        max(float(home_scored), float(away_scored)) <= 1.55 and
                        max(float(home_allowed or 0), float(away_allowed or 0)) <= 1.55):
                    return True, "DRAW_SA"

    # AWAY_SA — stronger away side in Serie A
    if (("серия а" in league or "serie a" in league or league == "sa")
            and match.odds_away is not None):
        if 2.05 <= float(match.odds_away) <= 3.60:
            if (away_w >= 3 and away_w - home_w >= 2 and away_stronger(3) and
                    float(away_scored or 0) >= 1.25 and float(home_allowed or 0) >= 1.35):
                return True, "AWAY_SA"

    # P1_PD — home side in La Liga
    if (("примера" in league or "la liga" in league or "laliga" in league or league == "pd" or league == "PD")
            and match.odds_home is not None):
        if 1.70 <= float(match.odds_home) <= 2.20:
            if (home_w >= 3 and home_w - away_w >= 1 and home_stronger(2) and
                    float(home_scored or 0) >= 1.30 and float(away_allowed or 0) >= 1.30):
                return True, "P1_PD"

    # PD_AWAY_VALUE — La Liga away value at odds 2.00-2.50
    if (("примера" in league or "la liga" in league or "laliga" in league or league == "pd")
            and match.odds_away is not None):
        if 2.00 <= float(match.odds_away) <= 2.50:
            away_name = (match.away_team or "").lower()
            if not any(t in away_name for t in ["сельта", "селта", "celta", "жирона", "girona", "валенс", "valencia"]):
                return True, "PD_AWAY_VALUE"

    # DRAW_BL1_FL1 — parity draw in Bundesliga / Ligue 1
    if (("бундеслига" in league or "bundesliga" in league or league == "bl1" or
         "лига 1" in league or "ligue 1" in league or league == "fl1")
            and match.odds_draw is not None and match.odds_home is not None and match.odds_away is not None):
        if 3.05 <= float(match.odds_draw) <= 3.70:
            if (close_table(4) and abs(home_w - away_w) <= 1 and
                    abs(float(match.odds_home) - float(match.odds_away)) <= 1.05 and
                    min(float(match.odds_home), float(match.odds_away)) >= 1.95 and
                    home_d + away_d >= 2):
                return True, "DRAW_BL1_FL1"

    # AWAY_BL1 — stronger away side in Bundesliga
    if (("бундеслига" in league or "bundesliga" in league or league == "bl1")
            and match.odds_away is not None):
        if 2.30 <= float(match.odds_away) <= 4.20:
            if (away_w >= 3 and home_w <= 1 and away_stronger(5) and
                    float(home_allowed or 0) >= 1.45):
                return True, "AWAY_BL1"

    # MLS_BTTS_HOME — MLS BTTS home, odds-based only (no form/standings needed)
    # Бэктест: ROI +11.5%, 6/6 сезонов, n=374, winrate=69.3%
    if match.odds_btts_yes is not None:
        btts = float(match.odds_btts_yes)
        if 1.50 <= btts <= 1.75:
            home = (match.home_team or "").lower()
            _MLS_HOME = [
                "интер майами", "портленд тимберс", "фк торонто", "торонто фк",
                "атланта юнайтед", "орландо сити", "нэшвилл",
                "лос-анджелес гэлакси", "лос-анджелес гэлэкси",
                "сан-хосе эртквейкс", "сан-хосе",
            ]
            if "сша" in league or "mls" in league:
                if any(t in home for t in _MLS_HOME):
                    return True, "MLS_BTTS_HOME"

    # SUMMER_BTTS_HOME — summer leagues BTTS home, odds-based only
    # Бэктест: ROI +22.8%, 5/5 сезонов, n=203, winrate=73.4%
    if match.odds_btts_yes is not None:
        btts = float(match.odds_btts_yes)
        if 1.55 <= btts <= 1.85:
            _SUMMER_KEYS = {"DNK", "SWE", "FIN"}
            _SUMMER_TEAMS = {
                "DNK": ["виборг", "оденсе", "норшелланн"],
                "SWE": ["хеккен"],
                "FIN": ["сик", "хака"],
            }
            for lk in _SUMMER_KEYS:
                if lk in league.upper():
                    home = (match.home_team or "").lower()
                    if any(t in home for t in _SUMMER_TEAMS[lk]):
                        try:
                            month = int(str(match.match_date or "")[:7].split("-")[1])
                            if 4 <= month <= 11:
                                return True, "SUMMER_BTTS_HOME"
                        except Exception:
                            pass

    return False, None


# ============================================================
# PRE-FLIGHT CHECK
# ============================================================

def pre_flight_check(facts: dict, sport: str) -> Optional[str]:
    """
    Фильтр до LLM. Правила берутся из sport_profiles.json → preflight_rules.
    """
    profile = get_profile(sport)
    rules = profile.get("preflight_rules", {})

    home_form = facts.get("form_last_5_home") or []
    away_form = facts.get("form_last_5_away") or []
    h2h = facts.get("h2h_summary") or ""
    home_pos = facts.get("home_position")
    away_pos = facts.get("away_position")
    home_scored = facts.get("home_goals_scored_avg")
    away_scored = facts.get("away_goals_scored_avg")
    notes = facts.get("notes") or ""

    has_standings = home_pos is not None or away_pos is not None
    has_form = len(home_form) >= 2 or len(away_form) >= 2
    has_goals = home_scored is not None or away_scored is not None
    has_injuries = "Травмы" in notes or "Injury" in notes

    # Правило 1: если вообще нет никаких данных
    if rules.get("require_any_data", True):
        if not has_standings and not has_form and not has_goals:
            return "Pre-flight: нет данных (standings, форма, голы) — PASS без LLM"

    # Правило 2: минимум формы для допуска к LLM
    min_form = rules.get("min_form_for_llm", 3)
    max_form = max(len(home_form), len(away_form))
    if max_form < min_form:
        return f"Pre-flight: форма < {min_form} матчей — PASS без LLM"

    # Правило 3: для football без lineups — проверяем наличие injury data
    if rules.get("require_injuries_for_medium_without_lineups", False):
        if not has_injuries:
            return "Pre-flight: football без lineups требует injury data — PASS без LLM"

    # Правило 4: для football без lineups — проверяем наличие таблицы
    if rules.get("require_table_for_medium_without_lineups", False):
        if not has_standings:
            return "Pre-flight: нет данных таблицы для Medium без составов — PASS без LLM"

    # Правило 5: спорт-специфичная блокировка (нет H2H + короткая форма + нет составов)
    if rules.get("block_if_no_h2h_and_short_form_and_no_lineups", False):
        threshold = rules.get("min_form_threshold_for_block", 3)
        min_form_both = min(len(home_form), len(away_form))
        if (not h2h.strip()
                and min_form_both < threshold
                and not facts.get("lineup_data_available")):
            return (f"Pre-flight {sport}: нет H2H + форма < {threshold} "
                    f"+ нет составов → PASS без LLM")

    # Правило 6: для football — нужна форма ОБЕИХ команд (не только одной)
    if sport == "football":
        both_have_form = len(home_form) >= 3 and len(away_form) >= 3
        if not both_have_form:
            return "Pre-flight: нет формы одной из команд (нужно 3+) — PASS без LLM"

    # Правило 4: Medium без составов требует достаточного объёма данных
    medium_reqs = profile.get("medium_without_lineups_requires")
    if medium_reqs and not facts.get("lineup_data_available"):
        min_form_req = medium_reqs.get("min_form_matches", 4)
        require_table = medium_reqs.get("require_table_data", True)

        min_form_both = min(len(home_form), len(away_form))
        has_table = (facts.get("home_position") is not None and
                     facts.get("away_position") is not None)

        if require_table and not has_table:
            return "Pre-flight: нет таблицы — Medium без составов невозможен → PASS без LLM"

        if min_form_both < min_form_req:
            return (f"Pre-flight: форма < {min_form_req} у обеих команд "
                    f"(min={min_form_both}) — Medium без составов невозможен → PASS без LLM")

    return None


# ============================================================
# CALIBRATION ENGINE
# ============================================================

def calibrate_probability(
    rec: Dict[str, Any],
    match: "Match",
    facts: Dict[str, Any],
    data_quality: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Единый движок калибровки. Все параметры из sport_profiles.json.
    """
    if rec.get("market") == "pass":
        return rec

    profile = get_profile(match.sport)
    our_p = float(rec.get("our_probability", 0.5))
    lineup_ok = bool(rec.get("lineup_data_available", False))
    signal = rec.get("signal_type", "Medium")
    adjustments = []

    # Store original probability for BTTS debug
    is_btts_market = rec.get("market", "").startswith("btts_")
    original_p = our_p

    # 1. CAP по составам — Weak и Medium имеют разные caps из профиля
    if not lineup_ok:
        if is_btts_market:
            # Softer cap for BTTS markets without lineups
            if signal == "Weak":
                cap = profile.get("weak_no_lineup_cap", profile["no_lineup_cap"] - 0.02) + 0.03
            else:
                cap = profile["no_lineup_cap"] + 0.03
            if our_p > cap:
                adjustments.append(f"cap без составов BTTS ({signal}) {our_p:.3f}→{cap:.3f}")
                our_p = cap
        else:
            # Standard cap for 1X2 markets
            if signal == "Weak":
                cap = profile.get("weak_no_lineup_cap", profile["no_lineup_cap"] - 0.02)
            else:
                cap = profile["no_lineup_cap"]
            if our_p > cap:
                adjustments.append(f"cap без составов ({signal}) {our_p:.3f}→{cap:.3f}")
                our_p = cap
    else:
        cap = profile["lineup_cap"]
        if our_p > cap:
            adjustments.append(f"cap с составами {our_p:.3f}→{cap:.3f}")
            our_p = cap

    # 1b. Корректировка по лиге (из бэктеста)
    league_conf = profile.get("league_confidence", {})
    league_factor = league_conf.get(match.league, 1.0)
    if league_factor != 1.0:
        old_p = our_p
        our_p = our_p * league_factor
        our_p = min(our_p, cap if not lineup_ok else profile["lineup_cap"])
        if abs(old_p - our_p) > 0.005:
            adjustments.append(f"лига {match.league.split('.')[0]} ×{league_factor} → {our_p:.3f}")

    # 2. Штраф за пустой H2H (из профиля)
    h2h = facts.get("h2h_summary") or ""
    penalty = profile.get("no_h2h_penalty", 0)
    if not h2h.strip() and penalty > 0:
        our_p -= penalty
        adjustments.append(f"штраф -{penalty} (нет H2H)")

    # 3. Штраф за неполную форму (из профиля)
    home_form = facts.get("form_last_5_home") or []
    away_form = facts.get("form_last_5_away") or []
    min_form = min(len(home_form), len(away_form))

    if min_form < 3:
        p = profile.get("short_form_penalty_3", 0.02)
        our_p -= p
        adjustments.append(f"штраф -{p} (форма<3, min={min_form})")
        # Доп. штраф если H2H тоже пустой (только для хоккея)
        if match.sport == "hockey" and not h2h.strip():
            extra = 0.02
            our_p -= extra
            adjustments.append(f"штраф -{extra} (H2H пустой + форма короткая)")
    elif min_form < 5:
        p = profile.get("short_form_penalty_5", 0.01)
        our_p -= p
        adjustments.append(f"штраф -{p} (форма<5, min={min_form})")

    # 4. Двухуровневый штраф: lineups vs injuries
    if not lineup_ok:
        notes = facts.get("notes") or ""
        has_injuries = bool((data_quality or {}).get("has_injuries")) if data_quality else (
            "Травмы" in notes or "Injury" in notes or "injury" in notes
        )

        # Считаем количество травм у каждой команды
        import re as _re
        home_inj_count = len(_re.findall(r'\b(?:Injury|Knee|Muscle|Ankle|Hamstring|Calf|Shin|Thigh|Head|Back|Broken|Suspended|Red Card)\b', notes))
        # Простая эвристика: если "Травмы X:" встречается дважды с 4+ игроками
        both_teams_injured = notes.count("Травмы") >= 2

        # Применяем разные штрафы для BTTS и 1X2 рынков
        if is_btts_market:
            # Reduced penalties for BTTS markets (50% reduction)
            if profile.get("allow_medium_without_lineups") and signal == "Medium":
                if has_injuries:
                    p = profile.get("lineups_missing_penalty", 0.01) * 0.5
                    if p > 0:
                        our_p -= p
                        adjustments.append(f"штраф -{p:.3f} (BTTS: нет lineups, но есть injury data)")

                    # Reduced additional penalty for BTTS when both teams injured
                    both_teams_injured = notes.count("Травмы") >= 2
                    home_inj_mentions = len(_re.findall(r'Травмы [^:]+: ([^|]+)', notes))
                    confirmed_out = len(_re.findall(
                        r'(?:Knee|Muscle|Broken|Hamstring|Ankle|Calf|Shin|Thigh|Back|Groin|'
                        r'Suspended|Red Card|Concussion|Foot Injury|Leg Injury)',
                        notes
                    ))
                    if both_teams_injured and confirmed_out >= 6:
                        extra = 0.005 * 0.5
                        our_p -= extra
                        adjustments.append(f"штраф -{extra:.3f} (BTTS: 4+ confirmed out у обеих команд)")
                else:
                    p1 = profile.get("lineups_missing_penalty", 0.01) * 0.5
                    p2 = profile.get("injuries_missing_penalty", 0.02) * 0.5
                    total = p1 + p2
                    our_p -= total
                    adjustments.append(f"штраф -{total:.3f} (BTTS: нет lineups + нет injury data)")
            elif signal == "Medium":
                p = profile.get("medium_no_lineup_penalty", 0.01) * 0.5
                if p > 0:
                    our_p -= p
                    adjustments.append(f"штраф -{p:.3f} (BTTS: Medium без составов)")
            elif signal == "Weak":
                p = profile.get("weak_no_lineup_penalty", 0.02) * 0.5
                if p > 0:
                    our_p -= p
                    adjustments.append(f"штраф -{p:.3f} (BTTS: Weak без составов)")
        else:
            # Standard penalties for 1X2 markets
            if profile.get("allow_medium_without_lineups") and signal == "Medium":
                if has_injuries:
                    p = profile.get("lineups_missing_penalty", 0.01)
                    if p > 0:
                        our_p -= p
                        adjustments.append(f"штраф -{p} (нет lineups, но есть injury data)")
                    # Доп. штраф если обе команды серьёзно травмированы — edge размывается
                    # Только если у обеих реально много потерь (4+ упоминаний травм)
                    both_teams_injured = notes.count("Травмы") >= 2
                    home_inj_mentions = len(_re.findall(r'Травмы [^:]+: ([^|]+)', notes))
                    # Считаем confirmed out (только серьёзные травмы, не Yellow Cards)
                    confirmed_out = len(_re.findall(
                        r'(?:Knee|Muscle|Broken|Hamstring|Ankle|Calf|Shin|Thigh|Back|Groin|'
                        r'Suspended|Red Card|Concussion|Foot Injury|Leg Injury)',
                        notes
                    ))
                    if both_teams_injured and confirmed_out >= 6:
                        extra = 0.005
                        our_p -= extra
                        adjustments.append(f"штраф -{extra} (4+ confirmed out у обеих команд)")
                else:
                    p1 = profile.get("lineups_missing_penalty", 0.01)
                    p2 = profile.get("injuries_missing_penalty", 0.02)
                    total = p1 + p2
                    our_p -= total
                    adjustments.append(f"штраф -{total} (нет lineups + нет injury data)")
            elif signal == "Medium":
                p = profile.get("medium_no_lineup_penalty", 0.01)
                if p > 0:
                    our_p -= p
                    adjustments.append(f"штраф -{p} (Medium без составов)")
            elif signal == "Weak":
                p = profile.get("weak_no_lineup_penalty", 0.02)
                if p > 0:
                    our_p -= p
                    adjustments.append(f"штраф -{p} (Weak без составов)")

    # 5. Floor — из профиля, не единый хардкод
    floor = profile.get("probability_floor", 0.35)
    our_p = max(our_p, floor)

    # 6. Защита от ставок на больших аутсайдеров без составов
    # Без confirmed lineups нельзя быть уверенным что аутсайдер @ 5.0+ выиграет
    if not lineup_ok and signal in ("Medium", "Weak"):
        market = rec.get("market", "")
        odds_map = {}
        # odds будут применены позже — используем our_p как proxy
        # Если наша вероятность < 25% без составов → слишком рискованно
        if our_p < 0.28:
            our_p = 0.28
            adjustments.append("floor 0.28 (аутсайдер без составов — риск переоценки)")

    rec["our_probability"] = round(our_p, 4)
    rec["probability_adjustments"] = adjustments

    # Store calibration info for BTTS debug
    if is_btts_market:
        rec["btts_calibration"] = {
            "original_p": original_p,
            "final_p": our_p,
            "adjustment": original_p - our_p,
            "adjustments": adjustments
        }

    return rec
